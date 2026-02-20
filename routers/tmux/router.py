"""
Tmux Manager Router
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, field_validator
from typing import Optional
import subprocess
import os
import yaml
import re

router = APIRouter(prefix="/api/tmux", tags=["tmux"])

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "tts_bot")

TTYD_PORT_RANGE_DEV = os.getenv("TTYD_PORT_RANGE_DEV", "15100-15300")
TTYD_PORT_RANGE_PROD = os.getenv("TTYD_PORT_RANGE_PROD", "15100-15300")
TTYD_BASE_URL = os.getenv("TTYD_BASE_URL", "")

def parse_port_range(port_range: str):
    start, end = port_range.split("-")
    return range(int(start), int(end) + 1)

class SessionCreate(BaseModel):
    name: str
    detached: bool = True

class WindowCreate(BaseModel):
    win_name: str
    session_name: str = "worker"
    dev: bool = False
    workspace: Optional[str] = None
    init_script: str = "pwd"
    use_local_ip: bool = False
    title: Optional[str] = None
    proxy: Optional[str] = None
    tg_token: Optional[str] = None
    tg_chat_id: Optional[str] = None
    tg_enable: bool = False
    
    @field_validator('win_name')
    @classmethod
    def validate_win_name(cls, v):
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('win_name must contain only alphanumeric characters and underscores')
        return v

class SessionRename(BaseModel):
    old_name: str
    new_name: str

class WindowRename(BaseModel):
    session: str
    old_name: str
    new_name: str

def run_tmux(cmd, check_session=False):
    """Execute tmux command using host socket
    If check_session=True, returns None for "no server/session" errors instead of raising
    """
    socket_path = os.getenv("TMUX_SOCKET", "/home/w3c_offical/.tmux/default")
    result = subprocess.run(["tmux", "-S", socket_path] + cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr.strip().lower()
        # If checking session existence, return None for not found errors
        if check_session and ("no server running" in err or "can't find session" in err or "can't find window" in err):
            return None
        raise HTTPException(status_code=400, detail=result.stderr.strip())
    return result.stdout.strip()

def is_yaml(request: Request) -> bool:
    return "application/yaml" in request.headers.get("accept", "").lower()

def format_response(data: dict, request: Request):
    if is_yaml(request):
        yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return PlainTextResponse(yaml_str, media_type="application/yaml")
    return data
def _load_api_token() -> str:
    import json as _json
    for path in ["/home/w3c_offical/global.json", os.path.expanduser("~/global.json")]:
        try:
            with open(path) as f:
                return _json.load(f).get("api_token", "")
        except Exception:
            pass
    return ""


def create_ttyd_pane_common(
    pane_id: str,
    session_name: str,
    win_name: str,
    workspace: str,
    init_script: str,
    proxy: str,
    title: str,
    dev: bool = False,
    tg_token: str = None,
    tg_chat_id: str = None,
    tg_enable: bool = False,
    clear_after_init: bool = False,
):
    import pymysql
    import socket
    import time

    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        cursorclass=pymysql.cursors.DictCursor
    )

    try:
        with conn.cursor() as c:

            # 1️⃣ 分配端口
            port_range = parse_port_range(
                TTYD_PORT_RANGE_DEV if dev else TTYD_PORT_RANGE_PROD
            )

            port = None
            for p in port_range:
                c.execute(
                    "SELECT 1 FROM ttyd_config WHERE ttyd_port=%s",
                    (p,)
                )
                if not c.fetchone():
                    port = p
                    break

            if not port:
                raise Exception("No available port")

            # 2️⃣ token (global) + url
            token = _load_api_token()
            url = f"https://g-ttyd.cicy.de5.net/?token={token}&bot_name={pane_id}"

            # 3️⃣ 写入 DB
            c.execute("""
                INSERT INTO ttyd_config
                (pane_id, title, ttyd_port, url, workspace, init_script, proxy, tg_token, tg_chat_id, tg_enable)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                pane_id,
                title,
                port,
                url,
                workspace,
                init_script,
                proxy,
                tg_token,
                tg_chat_id,
                tg_enable,
            ))

            conn.commit()

        # 4️⃣ 启动 ttyd (run-shell runs on host, bypassing docker PID isolation;
        #    send-keys fails from Python subprocess with "no current client")
        socket_path = os.getenv("TMUX_SOCKET", "/home/w3c_offical/.tmux/default")
        ttyd_cmd = (
            f"nohup ttyd -W -p {port} "
            f"-c user:{token} "
            f"tmux -S {socket_path} attach -t {pane_id} "
            f"> /tmp/ttyd_{port}.log 2>&1 &"
        )

        run_tmux(["run-shell", ttyd_cmd])

        # 5️⃣ proxy env vars (applied before init_script)
        if proxy:
            proxy_cmd = (
                f"export http_proxy='{proxy}' https_proxy='{proxy}' "
                f"HTTP_PROXY='{proxy}' HTTPS_PROXY='{proxy}' ALL_PROXY='{proxy}'"
            )
            run_tmux(["send-keys", "-t", pane_id, proxy_cmd, "Enter"])

        # 6️⃣ init_script (multi-step: sleep:N delays, key:X sends key without Enter, regular lines → Enter)
        if init_script:
            for line in init_script.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith('sleep:'):
                    try:
                        secs = float(line.split(':', 1)[1])
                        time.sleep(secs)
                    except (ValueError, IndexError):
                        pass
                elif line.startswith('key:'):
                    key_val = line.split(':', 1)[1]
                    run_tmux(["send-keys", "-t", pane_id, key_val])
                else:
                    run_tmux(["send-keys", "-t", pane_id, line, "Enter"])

        # 7️⃣ 可选：sleep + clear（create 时使用）
        if clear_after_init:
            time.sleep(1)
            run_tmux(["send-keys", "-t", pane_id, "clear", "Enter"])

        # 8️⃣ 等待 ttyd ready
        max_wait = 30
        elapsed = 0

        while elapsed < max_wait:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                sock.close()
                return {
                    "port": port,
                    "token": token,
                    "url": url
                }
            sock.close()
            time.sleep(0.5)
            elapsed += 0.5

        raise Exception("ttyd start timeout")

    finally:
        conn.close()


@router.get("/sessions")
async def list_sessions(request: Request):
    """List all tmux sessions"""
    try:
        output = run_tmux(["list-sessions", "-F", "#{session_name}|#{session_windows}|#{session_created}"])
        sessions = []
        for line in output.split('\n'):
            if line:
                name, windows, created = line.split('|')
                # Skip internal linked sessions (v_*) and auto sessions
                if name.startswith('v_') or name.startswith('auto'):
                    continue
                sessions.append({"name": name, "windows": int(windows), "created": int(created)})
        return format_response({"sessions": sessions}, request)
    except HTTPException as e:
        if "no server running" in str(e.detail):
            return format_response({"sessions": []}, request)
        raise

@router.post("/sessions")
async def create_session(data: SessionCreate, request: Request):
    """Create new session"""
    cmd = ["new-session", "-s", data.name]
    if data.detached:
        cmd.append("-d")
    run_tmux(cmd)
    return format_response({"success": True, "session": data.name}, request)

@router.delete("/sessions/{name}")
async def delete_session(name: str, request: Request):
    """Delete session"""
    run_tmux(["kill-session", "-t", name])
    return format_response({"success": True, "session": name}, request)

@router.put("/sessions/rename")
async def rename_session(data: SessionRename, request: Request):
    """Rename session"""
    run_tmux(["rename-session", "-t", data.old_name, data.new_name])
    return format_response({"success": True, "old_name": data.old_name, "new_name": data.new_name}, request)

@router.get("/sessions/{session}/windows")
async def list_windows(session: str, request: Request):
    """List windows in session"""
    output = run_tmux(["list-windows", "-t", session, "-F", "#{window_index}|#{window_name}|#{window_active}"])
    windows = []
    for line in output.split('\n'):
        if line:
            index, name, active = line.split('|')
            windows.append({"index": int(index), "name": name, "active": active == "1"})
    return format_response({"session": session, "windows": windows}, request)

@router.post("/panes/{pane_id}/restart")
async def restart_pane(pane_id: str, request: Request):
    """
    Restart pane:
    1. 查配置
    2. 杀 ttyd
    3. 删 DB
    4. 删 tmux pane
    5. 调用 create 公用逻辑重建
    """

    import pymysql
    import os
    import socket

    # 1️⃣ 读取旧配置
    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        cursorclass=pymysql.cursors.DictCursor
    )

    try:
        with conn.cursor() as c:
            c.execute("""
                SELECT ttyd_port, workspace, init_script, title, proxy
                FROM ttyd_config
                WHERE pane_id=%s
            """, (pane_id,))

            row = c.fetchone()
            if not row:
                return format_response(
                    {"success": False, "error": "Pane not found"},
                    request
                )

            port = row["ttyd_port"]
            workspace = row["workspace"]
            init_script = row["init_script"] or "pwd"
            title = row["title"] or pane_id
            proxy = row["proxy"]

            # 2️⃣ 杀 ttyd（通过 tmux run-shell 在 host 上执行，绕过 docker PID 隔离）
            # 同时按端口（已绑定）和 pane_id（未绑定的孤儿进程）杀，kill -9 确保立即退出
            try:
                run_tmux(["run-shell", (
                    # 按端口杀（已绑定的）
                    f"kill -9 $(lsof -ti:{port} 2>/dev/null) 2>/dev/null; "
                    # 按 pane_id 杀（未绑定的孤儿 ttyd 进程）
                    f"pkill -9 -f 'tmux attach -t {pane_id}' 2>/dev/null; "
                    # 等待端口释放（最多 2 秒）
                    f"for i in $(seq 1 20); do lsof -ti:{port} >/dev/null 2>&1 || break; sleep 0.1; done; true"
                )])
            except:
                pass

            # 3️⃣ 删 DB
            c.execute(
                "DELETE FROM ttyd_config WHERE pane_id=%s",
                (pane_id,)
            )
            conn.commit()

    finally:
        conn.close()

    # 4️⃣ 杀 tmux pane
    try:
        run_tmux(["kill-pane", "-t", pane_id])
    except:
        pass

    # 5️⃣ 解析 pane_id
    parts = pane_id.split(":")
    if len(parts) != 2:
        return format_response(
            {"success": False, "error": "Invalid pane_id"},
            request
        )

    session_name = parts[0]
    win_name = parts[1].split(".")[0]

    # 6️⃣ 创建新 tmux window，再调用公用创建逻辑
    try:
        run_tmux(["new-window", "-t", session_name, "-n", win_name, "-c", workspace or os.path.expanduser("~")])

        result = create_ttyd_pane_common(
            pane_id=pane_id,
            session_name=session_name,
            win_name=win_name,
            workspace=workspace,
            init_script=init_script,
            proxy=proxy,
            title=title,
            dev=False,
        )

        return format_response({
            "success": True,
            "message": "Pane restarted",
            "pane_id": pane_id,
            "port": result["port"],
            "url": result["url"]
        }, request)

    except Exception as e:
        return format_response({
            "success": False,
            "error": str(e)
        }, request)



@router.post("/create")
async def create_window(data: WindowCreate, request: Request):
    """Create tmux window and start ttyd (sync - wait for ttyd to start)"""
    import os

    host_home = os.getenv("HOST_HOME", os.path.expanduser("~"))
    workspace = data.workspace if data.workspace else f"{host_home}/workers/{data.win_name}"
    workspace_expanded = os.path.expanduser(workspace)

    os.makedirs(workspace_expanded, exist_ok=True)

    session_check = run_tmux(["has-session", "-t", data.session_name], check_session=True)

    if session_check is None:
        run_tmux(["new-session", "-d", "-s", data.session_name, "-n", data.win_name, "-c", workspace_expanded])
    else:
        windows_output = run_tmux(["list-windows", "-t", data.session_name, "-F", "#{window_name}"], check_session=False)
        if windows_output and data.win_name in windows_output.split('\n'):
            raise HTTPException(status_code=400, detail=f"Window '{data.win_name}' already exists in session '{data.session_name}'")
        run_tmux(["new-window", "-t", data.session_name, "-n", data.win_name, "-c", workspace_expanded], check_session=False)

    pane_id = f"{data.session_name}:{data.win_name}.0"
    title = data.title or pane_id

    # Set tmux dark theme colors
    run_tmux(["set-option", "-g", "status-style", "bg=#1e1e1e,fg=#888888"])
    run_tmux(["set-option", "-g", "window-status-current-style", "fg=#ffffff,bg=#2d2d2d"])
    run_tmux(["set-option", "-g", "pane-active-border-style", "fg=#4a9eff"])

    try:
        result = create_ttyd_pane_common(
            pane_id=pane_id,
            session_name=data.session_name,
            win_name=data.win_name,
            workspace=data.workspace or workspace_expanded,
            init_script=data.init_script,
            proxy=data.proxy,
            title=title,
            dev=data.dev,
            tg_token=data.tg_token,
            tg_chat_id=data.tg_chat_id,
            tg_enable=data.tg_enable,
            clear_after_init=True,
        )
    except Exception as e:
        return format_response({
            "success": False,
            "session": data.session_name,
            "window": data.win_name,
            "pane_id": pane_id,
            "error": str(e)
        }, request)

    return format_response({
        "success": True,
        "session": data.session_name,
        "window": data.win_name,
        "pane_id": pane_id,
        "title": title,
        "workspace": data.workspace,
        "init_script": data.init_script,
        "proxy": data.proxy,
        "tg_token": data.tg_token,
        "tg_chat_id": data.tg_chat_id,
        "tg_enable": data.tg_enable,
        "ttyd_port": result["port"],
        "url": result["url"]
    }, request)

@router.patch("/panes/{pane_id}")
async def update_pane(pane_id: str, request: Request, payload: dict):
    """Update pane fields"""
    import pymysql
    
    allowed_fields = ['title', 'workspace', 'init_script', 'proxy', 'tg_token', 'tg_chat_id', 'tg_enable']
    updates = {k: v for k, v in payload.items() if k in allowed_fields}
    
    if not updates:
        return format_response({"success": False, "error": "No valid fields to update"}, request)
    
    conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD, 
                          database=MYSQL_DATABASE, cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as c:
            set_clause = ", ".join([f"{k}=%s" for k in updates.keys()])
            values = list(updates.values())
            values.append(pane_id)
            c.execute(f"UPDATE ttyd_config SET {set_clause} WHERE pane_id=%s", values)
        conn.commit()
        return format_response({"success": True, "pane_id": pane_id, "updated": updates}, request)
    finally:
        conn.close()

@router.get("/panes/{pane_id}")
async def get_pane(pane_id: str, request: Request):
    """Get pane details"""
    import pymysql
    conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD, 
                          database=MYSQL_DATABASE, cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as c:
            c.execute("SELECT pane_id, title, ttyd_port, url, workspace, init_script, proxy, tg_token, tg_chat_id, tg_enable FROM ttyd_config WHERE pane_id=%s", (pane_id,))
            row = c.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Pane {pane_id} not found")
            return format_response({
                "pane_id": row["pane_id"],
                "title": row.get("title"),
                "ttyd_port": row["ttyd_port"],
                "url": row.get("url"),
                "workspace": row.get("workspace"),
                "init_script": row.get("init_script"),
                "proxy": row.get("proxy"),
                "tg_token": row.get("tg_token"),
                "tg_chat_id": row.get("tg_chat_id"),
                "tg_enable": row.get("tg_enable", False)
            }, request)
    finally:
        conn.close()

@router.delete("/panes/{pane_id}")
async def delete_pane(pane_id: str, request: Request):
    """Delete pane - kill tmux pane and remove database record"""
    import pymysql
    
    conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD, 
                          database=MYSQL_DATABASE, cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as c:
            c.execute("SELECT ttyd_port FROM ttyd_config WHERE pane_id=%s", (pane_id,))
            row = c.fetchone()
            if row:
                port = row.get("ttyd_port")
                if port:
                    # 通过 tmux run-shell 在 host 上杀进程，绕过 docker PID 隔离
                    try:
                        run_tmux(["run-shell", f"kill -9 $(lsof -ti:{port} 2>/dev/null) 2>/dev/null; true"])
                    except:
                        pass
                c.execute("DELETE FROM ttyd_config WHERE pane_id=%s", (pane_id,))
                conn.commit()
        
        try:
            run_tmux(["kill-pane", "-t", pane_id])
        except:
            pass
            
        return format_response({"success": True, "pane_id": pane_id, "message": "Pane deleted"}, request)
    finally:
        conn.close()


@router.delete("/sessions/{session}/windows/{window}")
async def delete_window(session: str, window: str, request: Request):
    """Delete window"""
    run_tmux(["kill-window", "-t", f"{session}:{window}"])
    return format_response({"success": True, "session": session, "window": window}, request)

@router.post("/sessions/{session}/windows/{window}/send")
async def send_to_window(session: str, window: str, request: Request, payload: dict):
    """Send text or keys to window"""
    # Use pane_id from payload if provided, otherwise default to .0
    pane = payload.get("pane_id", "0")
    win_id = f"{session}:{window}.{pane}"
    
    if "text" in payload:
        # Send literal text
        text = payload["text"].replace("'", "'\\''")
        run_tmux(["send-keys", "-t", win_id, "-l", text])
    elif "keys" in payload:
        # Send keys
        run_tmux(["send-keys", "-t", win_id, payload["keys"]])
    
    return format_response({"success": True, "win_id": win_id}, request)

@router.post("/send")
async def send_short(request: Request, payload: dict):
    """Send text or keys to window (short path)
    Payload: {"win_id": "session:window.pane", "text": "..."} or {"win_id": "...", "keys": "..."}
    """
    win_id = payload.get("win_id")
    if not win_id:
        return format_response({"error": "win_id required"}, request)
    
    if "text" in payload:
        text = payload["text"].replace("'", "'\\''")
        run_tmux(["send-keys", "-t", win_id, "-l", text])
    elif "keys" in payload:
        run_tmux(["send-keys", "-t", win_id, payload["keys"]])
    
    return format_response({"success": True, "win_id": win_id}, request)

@router.get("/tree")
async def tree(request: Request):
    """Get structured tree data"""
    try:
        sessions_output = run_tmux(["list-sessions", "-F", "#{session_name}"])
        session_names = [s for s in sessions_output.split('\n') if s]
        
        tree_data = []
        for session in session_names:
            windows_output = run_tmux(["list-windows", "-t", session, "-F", "#{window_index}|#{window_name}|#{window_active}"])
            windows = []
            for line in windows_output.split('\n'):
                if line:
                    index, name, active = line.split('|')
                    windows.append({
                        "index": int(index),
                        "name": name,
                        "active": active == "1",
                        "pane": f"{session}:{name}.0"
                    })
            
            tree_data.append({
                "session": session,
                "windows": windows
            })
        
        return format_response({"tree": tree_data}, request)
    except HTTPException as e:
        if "no server running" in str(e.detail):
            return format_response({"tree": []}, request)
        raise

@router.post("/clear")
async def clear_all(request: Request):
    """Clear all tmux sessions and panes"""
    try:
        run_tmux(["kill-server"])
    except HTTPException:
        pass
    return format_response({"success": True, "message": "All sessions cleared"}, request)

@router.post("/capture_pane")
async def capture_pane(request: Request, payload: dict):
    """Capture pane output
    Payload: {"pane_id": "session:window.pane", "start": -100, "end": -1}
    """
    pane_id = payload.get("pane_id")
    if not pane_id:
        return format_response({"error": "pane_id required"}, request)
    
    start = payload.get("start", "")
    end = payload.get("end", "")
    
    cmd = ["capture-pane", "-t", pane_id, "-p"]
    if start:
        cmd.extend(["-S", str(start)])
    if end:
        cmd.extend(["-E", str(end)])
    
    output = run_tmux(cmd)
    
    # Filter out ttyd debug logs (lines starting with timestamp like [2026/02/18...])
    lines = output.split('\n')
    filtered_lines = [line for line in lines if not line.strip().startswith('[')]
    filtered_output = '\n'.join(filtered_lines)
    
    return format_response({"pane_id": pane_id, "output": filtered_output}, request)
