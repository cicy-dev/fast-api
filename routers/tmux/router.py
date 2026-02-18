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

TTYD_PORT_RANGE_DEV = os.getenv("TTYD_PORT_RANGE_DEV", "16100-16200")
TTYD_PORT_RANGE_PROD = os.getenv("TTYD_PORT_RANGE_PROD", "15100-15300")

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
    accept = request.headers.get("accept", "")
    if "application/json" in accept.lower():
        return False
    return True

def format_response(data: dict, request: Request):
    if is_yaml(request):
        yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return PlainTextResponse(yaml_str, media_type="application/yaml")
    return data

@router.get("/sessions")
async def list_sessions(request: Request):
    """List all tmux sessions"""
    try:
        output = run_tmux(["list-sessions", "-F", "#{session_name}|#{session_windows}|#{session_created}"])
        sessions = []
        for line in output.split('\n'):
            if line:
                name, windows, created = line.split('|')
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

@router.post("/create")
async def create_window(data: WindowCreate, request: Request):
    """Create tmux window and start ttyd (sync - wait for ttyd to start)"""
    import pymysql
    import secrets
    import requests
    import os
    import subprocess
    import time
    import socket
    
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
    
    if data.use_local_ip:
        pub_ip = "127.0.0.1"
    else:
        try:
            pub_ip = requests.get("https://api.myip.com", timeout=3).json()["ip"]
        except:
            pub_ip = "localhost"
    
    conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD, 
                          database=MYSQL_DATABASE, cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as c:
            port_range = parse_port_range(TTYD_PORT_RANGE_DEV) if data.dev else parse_port_range(TTYD_PORT_RANGE_PROD)
            port = None
            for p in port_range:
                c.execute("SELECT 1 FROM ttyd_config WHERE ttyd_port=%s", (p,))
                if c.fetchone():
                    continue
                port = p
                break
            
            if not port:
                raise HTTPException(status_code=400, detail="Port range exhausted")
            
            token = secrets.token_urlsafe(32)
            url = f"http://user:{token}@{pub_ip}:{port}/"
            title = data.title or pane_id
            c.execute("INSERT INTO ttyd_config (pane_id, title, ttyd_port, ttyd_token, url) VALUES (%s, %s, %s, %s, %s)",
                     (pane_id, title, port, token, url))
        conn.commit()
        
        # Set tmux dark theme colors
        run_tmux(["set-option", "-g", "status-style", "bg=#1e1e1e,fg=#888888"])
        run_tmux(["set-option", "-g", "window-status-current-style", "fg=#ffffff,bg=#2d2d2d"])
        run_tmux(["set-option", "-g", "pane-active-border-style", "fg=#4a9eff"])
        
        # Start ttyd in background with log redirection
        ttyd_cmd = f"nohup ttyd -W -p {port} -c user:{token} tmux attach -t {pane_id} > /tmp/ttyd_{port}.log 2>&1 &"
        run_tmux(["send-keys", "-t", pane_id, ttyd_cmd, "Enter"])

        if data.init_script:
            run_tmux(["send-keys", "-t", pane_id, data.init_script, "Enter"])
        
        time.sleep(1)
        run_tmux(["send-keys", "-t", pane_id, "clear", "Enter"])

        
        # run_tmux(["send-keys", "-t", pane_id, f"ttyd -W -p {port} -c user:{token} tmux attach -t {pane_id} &", "Enter"])
        
        # Wait for ttyd to be ready (max 30 seconds)
        max_wait = 30
        wait_interval = 0.5
        elapsed = 0
        ttyd_ready = False
        
        while elapsed < max_wait:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('127.0.0.1', port))
                sock.close()
                if result == 0:
                    ttyd_ready = True
                    break
            except:
                pass
            time.sleep(wait_interval)
            elapsed += wait_interval
        
        if not ttyd_ready:
            return format_response({
                "success": False,
                "session": data.session_name,
                "window": data.win_name,
                "pane_id": pane_id,
                "ttyd_port": port,
                "ttyd_token": token,
                "url": url,
                "error": "ttyd failed to start within 30 seconds"
            }, request)
        
        return format_response({
            "success": True,
            "session": data.session_name,
            "window": data.win_name,
            "pane_id": pane_id,
            "title": title,
            "ttyd_port": port,
            "ttyd_token": token,
            "url": url
        }, request)
    finally:
        conn.close()

@router.patch("/panes/{pane_id}/title")
async def update_pane_title(pane_id: str, request: Request, payload: dict):
    """Update pane title"""
    import pymysql
    title = payload.get('title', '')
    conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD, 
                          database=MYSQL_DATABASE, cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as c:
            c.execute("UPDATE ttyd_config SET title=%s WHERE pane_id=%s", (title, pane_id))
        conn.commit()
        return format_response({"success": True, "pane_id": pane_id, "title": title}, request)
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
