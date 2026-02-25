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
TTYD_BINARY_PATH = os.getenv("TTYD_BINARY_PATH", "ttyd")

def parse_port_range(port_range: str):
    start, end = port_range.split("-")
    return range(int(start), int(end) + 1)


class WindowCreate(BaseModel):
    win_name: Optional[str] = None
    dev: bool = False
    workspace: Optional[str] = None
    init_script: str = "pwd"
    use_local_ip: bool = False
    title: Optional[str] = None
    proxy: Optional[str] = None
    tg_token: Optional[str] = None
    tg_chat_id: Optional[str] = None
    tg_enable: bool = False
    
    # @field_validator('win_name')
    # @classmethod
    # def validate_win_name(cls, v):
    #     if not re.match(r'^[a-zA-Z0-9_]+$', v):
    #         raise ValueError('win_name must contain only alphanumeric characters and underscores')
    #     return v

class WindowRename(BaseModel):
    session: str
    old_name: str
    new_name: str

def run_tmux(cmd, check_session=False):
    """Execute tmux command using host socket
    If check_session=True, returns None for "no server/session" errors instead of raising
    """
    result = subprocess.run(["tmux"] + cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr.strip().lower()
    
        # If checking session existence, return None for not found errors
        if check_session and ("no server running" in err or "can't find session" in err or "can't find window" in err):
            # call #/panes/{pane_id}/restart and return run_tmux
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

def short_pane_id(pane_id: str) -> str:
    """w-20074:main.0 -> w-20074"""
    return pane_id.replace(":main.0", "") if pane_id else pane_id

def normalize_pane_id(pane_id: str) -> str:
    """Normalize pane_id: w-20074 -> w-20074:main.0"""
    if not pane_id:
        return pane_id
    if ':' not in pane_id:
        return f"{pane_id}:main.0"
    return pane_id

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
    ttyd_port:int,
    workspace: str,
    init_script: str,
    proxy: str,
    title: str,
    dev: bool = False,
    tg_token: str = None,
    tg_chat_id: str = None,
    tg_enable: bool = False,
    clear_after_init: bool = False,
    no_insert_db: bool = False,
):
    import pymysql
    import socket
    import time
    port = ttyd_port

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
            # 2️⃣ token (global)
            token = _load_api_token()

            if no_insert_db is False:
                # 3️⃣ 写入 DB
                c.execute("""
                    INSERT INTO ttyd_config
                    (pane_id, title, ttyd_port, workspace, init_script, proxy, tg_token, tg_chat_id, tg_enable, created_at, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW(), NOW())
                """, (
                    pane_id,
                    title,
                    ttyd_port,
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
        ttyd_cmd = (
            f"nohup {TTYD_BINARY_PATH} -W -p {ttyd_port} "
            f"-c user:{token} "
            f"tmux attach -t {pane_id} "
            f"> /tmp/ttyd_{ttyd_port}.log 2>&1 &"
        )

        run_tmux(["run-shell", ttyd_cmd])

        # 5️⃣ export X_PANE_ID
        run_tmux(["send-keys", "-t", pane_id, f"export X_PANE_ID='{pane_id}'", "Enter"])

        # 5.5️⃣ proxy env vars (applied before init_script)
        # Format: "http://host:port" (plain) or "mitmproxy:http://host:port" (adds REQUESTS_CA_BUNDLE)
        if proxy:
            is_mitmproxy = proxy.startswith("mitmproxy:")
            proxy_url = proxy[len("mitmproxy:"):] if is_mitmproxy else proxy
            proxy_cmd = (
                f"export http_proxy='{proxy_url}' https_proxy='{proxy_url}' "
                f"HTTP_PROXY='{proxy_url}' HTTPS_PROXY='{proxy_url}' ALL_PROXY='{proxy_url}'"
            )
            if is_mitmproxy:
                cert = "/home/w3c_offical/.mitmproxy/mitmproxy-ca-cert.pem"
                proxy_cmd += (
                    f" REQUESTS_CA_BUNDLE='{cert}'"
                    f" SSL_CERT_FILE='{cert}'"
                    f" NODE_EXTRA_CA_CERTS='{cert}'"
                )
            run_tmux(["send-keys", "-t", pane_id, proxy_cmd, "Enter"])

        # 6️⃣ clear screen before init_script
        run_tmux(["send-keys", "-t", pane_id, "clear", "Enter"])
        time.sleep(0.3)
        run_tmux(["send-keys", "-t", pane_id, "clear", "Enter"])

        # 6.5️⃣ Auto cd to workspace
        if workspace:
            workspace_expanded = workspace.replace('~', '/home/w3c_offical')
            run_tmux(["send-keys", "-t", pane_id, f"cd {workspace_expanded}", "Enter"])

        # 7️⃣ init_script (multi-step: sleep:N delays, key:X sends key without Enter, regular lines → Enter)
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
                    "token": token
                }
            sock.close()
            time.sleep(0.5)
            elapsed += 0.5

        raise Exception("ttyd start timeout")

    finally:
        conn.close()
@router.post("/panes/{pane_id}/restart")
async def restart_pane(pane_id: str, request: Request):
    pane_id = normalize_pane_id(pane_id)
    """
    改进版重启：
    1. 检索配置
    2. 杀掉占用该端口的 ttyd 进程
    3. 清理 tmux 窗格中的运行进程 (C-c) 并清屏
    4. 重新执行环境变量设置和 init_script
    5. 重新拉起 ttyd
    """
    import pymysql
    import time

    conn = pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE, cursorclass=pymysql.cursors.DictCursor
    )

    try:
        with conn.cursor() as c:
            c.execute("""
                SELECT ttyd_port, workspace, init_script, title, proxy, tg_token, tg_chat_id, tg_enable 
                FROM ttyd_config WHERE pane_id=%s
            """, (pane_id,))
            row = c.fetchone()
            if not row:
                return format_response({"success": False, "error": "数据库中未找到该 Pane 配置"}, request)

        # --- 1. 杀掉旧的 ttyd 进程 (只杀 ttyd，不杀 tmux) ---
        port = row["ttyd_port"]
        subprocess.run(f"pkill -f 'ttyd.*-p {port} '", shell=True, capture_output=True)
        time.sleep(0.5)

        # --- 2. 检查并恢复 tmux 状态 ---
        # 直接杀掉旧 session 并重建，确保干净状态
        session_name = pane_id.split(":")[0]
        try:
            run_tmux(["kill-session", "-t", session_name])
        except:
            pass
        time.sleep(0.3)
        
        workspace_expanded = os.path.expanduser(row["workspace"] or "~")
        run_tmux(["new-session", "-d", "-s", session_name, "-n", "main", "-c", workspace_expanded])

        # --- 3. 调用公共逻辑重新初始化 (不插入DB) ---
        result = create_ttyd_pane_common(
            pane_id=pane_id,
            session_name=session_name,
            win_name="main",
            ttyd_port=int(port),
            workspace=row["workspace"],
            init_script=row["init_script"],
            proxy=row["proxy"],
            title=row["title"],
            tg_token=row["tg_token"],
            tg_chat_id=row["tg_chat_id"],
            tg_enable=row["tg_enable"],
            clear_after_init=True,
            no_insert_db=True  # 核心：避免主键冲突
        )

        # 更新数据库时间
        with conn.cursor() as c:
            c.execute("UPDATE ttyd_config SET updated_at=NOW() WHERE pane_id=%s", (pane_id,))
            conn.commit()

        return format_response({
            "success": True,
            "message": "Pane 软重启完成"
        }, request)

    except Exception as e:
        return format_response({"success": False, "error": str(e)}, request)
    finally:
        conn.close()


def _get_next_worker_index() -> int:
    import pymysql
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
            c.execute("SELECT value FROM global_vars WHERE key_name='worker_index'")
            row = c.fetchone()
            if row:
                current = int(row["value"])
            else:
                current = 20000
            next_idx = current + 1
            c.execute(
                "INSERT INTO global_vars (key_name, value) VALUES ('worker_index', %s) "
                "ON DUPLICATE KEY UPDATE value=%s",
                (str(next_idx), str(next_idx))
            )
            conn.commit()
            return next_idx
    finally:
        conn.close()


@router.get("/panes")
async def list_panes(request: Request, group_id: Optional[int] = None):
    """List all panes, optionally filtered by group_id
    
    Query params:
    - group_id: filter by group (optional)
    
    Returns: {"panes": [{pane_id, title, ttyd_port, workspace, group_id, active, created_at}]}
    """
    from db_pool import get_db
    
    with get_db() as conn:
        with conn.cursor() as c:
            if group_id is not None:
                c.execute("""
                    SELECT DISTINCT t.pane_id, t.title, t.ttyd_port, t.workspace, 
                           t.init_script, t.proxy, t.active, t.created_at, t.updated_at,
                           gp.group_id
                    FROM ttyd_config t
                    INNER JOIN ttyd_group_panes gp ON t.pane_id = gp.pane_id
                    WHERE gp.group_id = %s
                    ORDER BY t.created_at DESC
                """, (group_id,))
            else:
                c.execute("""
                    SELECT t.pane_id, t.title, t.ttyd_port, t.workspace, 
                           t.init_script, t.proxy, t.active, t.created_at, t.updated_at,
                           gp.group_id
                    FROM ttyd_config t
                    LEFT JOIN ttyd_group_panes gp ON t.pane_id = gp.pane_id
                    ORDER BY t.created_at DESC
                """)
            
            panes = c.fetchall()
            
            # Convert datetime to string
            for p in panes:
                if p.get('created_at'):
                    p['created_at'] = p['created_at'].isoformat()
                if p.get('updated_at'):
                    p['updated_at'] = p['updated_at'].isoformat()
            
            return format_response({"panes": panes}, request)

@router.post("/create")
async def create_window(data: WindowCreate, request: Request):
    """Create tmux session and start ttyd (each pane has its own unique session)"""
    import os
    import pymysql
    
    worker_index = _get_next_worker_index()
    unique_session = f"w-{worker_index}"
    title = data.win_name or unique_session
    host_home = os.getenv("HOST_HOME", os.path.expanduser("~"))
    workspace = data.workspace if data.workspace else f"{host_home}/workers/{unique_session}"
    workspace_expanded = os.path.expanduser(workspace)

    os.makedirs(workspace_expanded, exist_ok=True)
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
            c.execute("SELECT pane_id FROM ttyd_config WHERE pane_id=%s", (f"{unique_session}:main.0",))
            if c.fetchone():
                raise HTTPException(status_code=400, detail=f"Pane '{unique_session}' already exists")
    finally:
        conn.close()

    session_check = run_tmux(["has-session", "-t", unique_session], check_session=True)

    if session_check is not None:
        raise HTTPException(status_code=400, detail=f"Session '{unique_session}' already exists")

    run_tmux(["new-session", "-d", "-s", unique_session, "-n", "main", "-c", workspace_expanded])

    pane_id = f"{unique_session}:main.0"

    run_tmux(["set-option", "-g", "status-style", "bg=#1e1e1e,fg=#888888"])
    run_tmux(["set-option", "-g", "window-status-current-style", "fg=#ffffff,bg=#2d2d2d"])
    run_tmux(["set-option", "-g", "pane-active-border-style", "fg=#4a9eff"])

    try:
        result = create_ttyd_pane_common(
            pane_id=pane_id,
            session_name=unique_session,
            win_name="main",
            ttyd_port=int(worker_index),
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
        try:
            run_tmux(["kill-session", "-t", unique_session])
        except:
            pass
        return format_response({
            "success": False,
            "session": unique_session,
            "window": "main",
            "pane_id": short_pane_id(pane_id),
            "error": str(e)
        }, request)

    return format_response({
        "success": True,
        "session": unique_session,
        "window": "main",
        "pane_id": short_pane_id(pane_id),
        "title": title,
        "workspace": data.workspace,
        "init_script": data.init_script,
        "proxy": data.proxy,
        "tg_token": data.tg_token,
        "tg_chat_id": data.tg_chat_id,
        "tg_enable": data.tg_enable,
        "ttyd_port": result["port"]
    }, request)

@router.patch("/panes/{pane_id}")
async def update_pane(pane_id: str, request: Request, payload: dict):
    pane_id = normalize_pane_id(pane_id)
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
        return format_response({"success": True, "pane_id": short_pane_id(pane_id), "updated": updates}, request)
    finally:
        conn.close()

@router.get("/panes/{pane_id}")
async def get_pane(pane_id: str, request: Request):
    pane_id = normalize_pane_id(pane_id)
    """Get pane details"""
    from db_pool import get_db
    
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("""
                SELECT t.pane_id, t.title, t.ttyd_port, t.workspace, t.init_script, 
                       t.proxy, t.tg_token, t.tg_chat_id, t.tg_enable, gp.group_id
                FROM ttyd_config t
                LEFT JOIN ttyd_group_panes gp ON t.pane_id = gp.pane_id
                WHERE t.pane_id = %s
            """, (pane_id,))
            row = c.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Pane {pane_id} not found")
            return format_response({
                "pane_id": short_pane_id(row["pane_id"]),
                "title": row.get("title"),
                "ttyd_port": row["ttyd_port"],
                "workspace": row.get("workspace"),
                "init_script": row.get("init_script"),
                "proxy": row.get("proxy"),
                "tg_token": row.get("tg_token"),
                "tg_chat_id": row.get("tg_chat_id"),
                "tg_enable": row.get("tg_enable", False),
                "group_id": row.get("group_id")
            }, request)

@router.delete("/panes/{pane_id}")
async def delete_pane(pane_id: str, request: Request):
    pane_id = normalize_pane_id(pane_id)
    """Delete pane - kill tmux session and remove database record"""
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
                    try:
                        run_tmux(["run-shell", f"kill -9 $(lsof -ti:{port} 2>/dev/null) 2>/dev/null; true"])
                    except:
                        pass
                c.execute("DELETE FROM ttyd_config WHERE pane_id=%s", (pane_id,))
                conn.commit()
        
        session_name = pane_id.split(":")[0] if ":" in pane_id else pane_id
        try:
            run_tmux(["kill-session", "-t", session_name])
        except:
            pass
            
        return format_response({"success": True, "pane_id": short_pane_id(pane_id), "message": "Pane deleted"}, request)
    finally:
        conn.close()

@router.post("/send")
async def send_short(request: Request, payload: dict):
    """Send text or keys to window (short path)
    Payload: {"win_id": "session:window.pane", "text": "..."} or {"win_id": "...", "keys": "..."}
    """
    win_id = payload.get("win_id")
    win_id = normalize_pane_id(win_id)
    if not win_id:
        return format_response({"error": "win_id required"}, request)
    
    if "text" in payload:
        text = payload["text"].replace("'", "'\\''")
        run_tmux(["send-keys", "-t", win_id, "-l", text])
        import time
        time.sleep(0.5)
        run_tmux(["send-keys", "-t", win_id, "Enter"])
    elif "keys" in payload:
        run_tmux(["send-keys", "-t", win_id, payload["keys"]])
    
    return format_response({"success": True, "win_id": short_pane_id(win_id)}, request)

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
    pane_id = normalize_pane_id(pane_id)
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
    
    return format_response({"pane_id": short_pane_id(pane_id), "output": filtered_output}, request)

@router.post("/send_wait")
async def send_wait(request: Request, payload: dict):
    """Send text to pane and wait for prompt to return
    Payload: {
        "target": "w-20074" or "w-20074:main.0" or "@title",
        "text": "command to execute",
        "prompt_type": "kiro-cli" (default) or "bash",
        "timeout": 60 (default, max 120)
    }
    """
    import time
    import pymysql
    
    target = payload.get("target")
    text = payload.get("text")
    prompt_type = payload.get("prompt_type", "kiro-cli")
    timeout = min(int(payload.get("timeout", 60)), 120)
    
    if not target or not text:
        return format_response({"success": False, "error": "target and text required"}, request)
    
    # Resolve target to pane_id
    pane_id = target
    if target.startswith("@"):
        title = target[1:]
        conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, 
                              password=MYSQL_PASSWORD, database=MYSQL_DATABASE, 
                              cursorclass=pymysql.cursors.DictCursor)
        try:
            with conn.cursor() as c:
                c.execute("SELECT pane_id FROM ttyd_config WHERE title=%s LIMIT 1", (title,))
                row = c.fetchone()
                if not row:
                    return format_response({"success": False, "error": f"No pane found with title '{title}'"}, request)
                pane_id = row["pane_id"]
        finally:
            conn.close()
    elif ":" not in target and target.startswith("w-"):
        pane_id = f"{target}:main.0"
    
    # Prompt patterns
    if prompt_type == "kiro-cli":
        prompt_pattern = re.compile(r'\d+%\s*>\s*$')
    elif prompt_type == "bash":
        prompt_pattern = re.compile(r'w-\d+\s+\$\s*$')
    else:
        return format_response({"success": False, "error": f"Invalid prompt_type: {prompt_type}"}, request)
    
    # 1. Capture baseline
    try:
        baseline_output = run_tmux(["capture-pane", "-t", pane_id, "-p"])
    except HTTPException as e:
        return format_response({"success": False, "error": f"Failed to capture baseline: {e.detail}"}, request)
    
    baseline_lines = [l for l in baseline_output.split('\n') if not l.strip().startswith('[')]
    baseline_len = len(baseline_lines)
    
    # 2. Send text with Enter
    try:
        text_escaped = text.replace("'", "'\\''")
        run_tmux(["send-keys", "-t", pane_id, "-l", text_escaped])
        run_tmux(["send-keys", "-t", pane_id, "Enter"])
    except HTTPException as e:
        return format_response({"success": False, "error": f"Failed to send text: {e.detail}"}, request)
    
    # 3. Poll for prompt
    start_time = time.time()
    answer = ""
    
    while time.time() - start_time < timeout:
        time.sleep(1)
        
        try:
            current_output = run_tmux(["capture-pane", "-t", pane_id, "-p"])
        except HTTPException:
            continue
        
        current_lines = [l for l in current_output.split('\n') if not l.strip().startswith('[')]
        
        # Check if prompt appeared at the end
        if len(current_lines) > 0:
            last_line = current_lines[-1].rstrip()
            if prompt_pattern.search(last_line):
                # Extract new output (everything after baseline)
                new_lines = current_lines[baseline_len:]
                answer = '\n'.join(new_lines).strip()
                
                return format_response({
                    "success": True,
                    "pane_id": short_pane_id(pane_id),
                    "question": text,
                    "answer": answer
                }, request)
    
    # Timeout
    return format_response({
        "success": False,
        "pane_id": short_pane_id(pane_id),
        "question": text,
        "error": f"Timeout after {timeout}s waiting for prompt"
    }, request)
