#!/usr/bin/env python3
"""
Ttyd Service - 按需启动 ttyd
"""

import os
import subprocess
import pymysql
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
import yaml

router = APIRouter(prefix="/api/ttyd", tags=["ttyd"])

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "tts_bot")

TTYD_PORT_RANGE_DEV = os.getenv("TTYD_PORT_RANGE_DEV", "15100-15300")
TTYD_PORT_RANGE_PROD = os.getenv("TTYD_PORT_RANGE_PROD", "15100-15300")

TTYD_BASE_URL = os.getenv("TTYD_BASE_URL", "")
TTYD_BINARY_PATH = os.getenv("TTYD_BINARY_PATH", "ttyd")

def _load_api_token() -> str:
    import json as _json
    for path in ["/home/w3c_offical/global.json", os.path.expanduser("~/global.json")]:
        try:
            with open(path) as f:
                return _json.load(f).get("api_token", "")
        except Exception:
            pass
    return ""

def get_db():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        cursorclass=pymysql.cursors.DictCursor
    )

def format_response(data: dict, request: Request = None):
    if request and "application/yaml" in request.headers.get("accept", "").lower():
        yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return PlainTextResponse(yaml_str, media_type="application/yaml")
    return data

def run_tmux(cmd):
    result = subprocess.run(["tmux"] + cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=result.stderr.strip())
    return result.stdout.strip()

def is_port_listening(port: int) -> bool:
    result = subprocess.run(["ss", "-tln"], capture_output=True, text=True)
    return f":{port}" in result.stdout

def parse_port_range(port_range: str):
    start, end = port_range.split("-")
    return range(int(start), int(end) + 1)

def _tmux_pane_exists(pane_id: str) -> bool:
    """Check if a tmux pane exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", pane_id.split(".")[0]],
        capture_output=True
    )
    return result.returncode == 0

def _allocate_port(cursor) -> int:
    """Find the next free port in the configured range."""
    port_range = parse_port_range(TTYD_PORT_RANGE_PROD)
    cursor.execute("SELECT ttyd_port FROM ttyd_config")
    used = {row["ttyd_port"] for row in cursor.fetchall()}
    for port in port_range:
        if port not in used:
            return port
    raise HTTPException(status_code=503, detail="No available ports in range")

@router.post("/start/{pane_id:path}")
async def start_ttyd(pane_id: str, request: Request):
    """按需启动 ttyd，如果已运行则返回现有配置；若 pane 存在但无配置则自动注册"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT * FROM ttyd_config WHERE pane_id=%s", (pane_id,))
            row = c.fetchone()

            if not row:
                # Reject internal linked sessions from being auto-provisioned
                session_part = pane_id.split(":")[0]
                if session_part.startswith("v_") or session_part.startswith("auto"):
                    raise HTTPException(status_code=400, detail=f"pane_id {pane_id} is an internal session")
                # Auto-provision: register the pane if it exists in tmux
                if not _tmux_pane_exists(pane_id):
                    raise HTTPException(status_code=404, detail=f"pane_id {pane_id} not found")
                port = _allocate_port(c)
                c.execute(
                    "INSERT INTO ttyd_config (pane_id, title, ttyd_port) VALUES (%s, %s, %s)",
                    (pane_id, pane_id, port)
                )
                conn.commit()
                c.execute("SELECT * FROM ttyd_config WHERE pane_id=%s", (pane_id,))
                row = c.fetchone()
            
            port = row["ttyd_port"]
            token = _load_api_token()
            title = row.get("title", pane_id)
            workspace = row.get("workspace")
            init_script = row.get("init_script")
            proxy = row.get("proxy")
            tg_token = row.get("tg_token")
            tg_chat_id = row.get("tg_chat_id")
            tg_enable = row.get("tg_enable", False)
            
            if is_port_listening(port):
                return format_response({
                    "pane_id": pane_id,
                    "title": title,
                    "port": port,
                    "token": token,
                    "url": row.get("url"),
                    "workspace": workspace,
                    "init_script": init_script,
                    "proxy": proxy,
                    "tg_token": tg_token,
                    "tg_chat_id": tg_chat_id,
                    "tg_enable": tg_enable,
                    "active": bool(row.get("active", True)),
                    "status": "running"
                }, request)

            # Apply proxy env vars if configured (before starting ttyd)
            if proxy:
                proxy_cmd = (
                    f"export http_proxy='{proxy}' https_proxy='{proxy}' "
                    f"HTTP_PROXY='{proxy}' HTTPS_PROXY='{proxy}' ALL_PROXY='{proxy}'"
                )
                run_tmux(["send-keys", "-t", pane_id, proxy_cmd, "Enter"])

            # Create a linked session per pane so Ctrl+B only affects this pane's clients.
            # pane_id format: "session:window.pane" e.g. "worker:chatgpt.0"
            _parts = pane_id.split(":")
            _base_session = _parts[0]  # "worker"
            _window_name = _parts[1].split(".")[0] if len(_parts) > 1 else pane_id  # "chatgpt"
            _view_session = f"v_{_window_name}"  # "v_chatgpt"
            # ignore error if session already exists
            subprocess.run(["tmux", "new-session", "-d", "-s", _view_session, "-t", _base_session], capture_output=True)
            run_tmux(["select-window", "-t", f"{_view_session}:{_window_name}"])

            # run-shell executes on the host (bypasses docker PID isolation);
            # send-keys fails from Python subprocess with "no current client"
            run_tmux([
                "run-shell",
                f"nohup {TTYD_BINARY_PATH} -W -p {port} -c user:{token} --style /home/w3c_offical/.ttyd-style.css "
                f"tmux attach -t {_view_session} "
                f"> /home/w3c_offical/projects/ai-workers/fast-api/logs/ttyd_{port}.log 2>&1 &"
            ])
            
            return format_response({
                "pane_id": pane_id,
                "title": title,
                "port": port,
                "token": token,
                "url": row.get("url"),
                "workspace": workspace,
                "init_script": init_script,
                "proxy": proxy,
                "tg_token": tg_token,
                "tg_chat_id": tg_chat_id,
                "tg_enable": tg_enable,
                "active": bool(row.get("active", True)),
                "status": "started"
            }, request)
    finally:
        conn.close()

@router.get("/status/{pane_id:path}")
async def get_status(pane_id: str, request: Request):
    """检查 ttyd 是否已启动"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT ttyd_port FROM ttyd_config WHERE pane_id=%s", (pane_id,))
            row = c.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail="pane_id not found")
            
            port = row["ttyd_port"]
            listening = is_port_listening(port)
            
            return format_response({
                "pane_id": pane_id,
                "port": port,
                "ready": listening
            }, request)
    finally:
        conn.close()

@router.get("/by-name/{name}")
async def get_by_name(name: str, request: Request):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT * FROM ttyd_config WHERE pane_id=%s", (name,))
            row = c.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="not found")
            return format_response({
                "pane_id": row["pane_id"],
                "port": row["ttyd_port"],
                "token": _load_api_token(),
                "url": row.get("url")
            }, request)
    finally:
        conn.close()

@router.get("/list")
async def list_configs(request: Request):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT pane_id, title, ttyd_port, active, created_at, updated_at FROM ttyd_config ORDER BY COALESCE(updated_at, created_at) DESC")
            rows = c.fetchall()
            for row in rows:
                if row.get("created_at"):
                    row["created_at"] = row["created_at"].isoformat()
                if row.get("updated_at"):
                    row["updated_at"] = row["updated_at"].isoformat()
            return format_response({"configs": rows}, request)
    finally:
        conn.close()

@router.delete("/config/{pane_id:path}")
async def delete_config(pane_id: str, request: Request):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM ttyd_config WHERE pane_id=%s", (pane_id,))
            conn.commit()
            return format_response({"success": True, "pane_id": pane_id}, request)
    finally:
        conn.close()

@router.patch("/config/{pane_id:path}")
async def update_config(pane_id: str, request: Request):
    """更新配置字段（title, workspace, init_script, proxy, tg_token, tg_chat_id, tg_enable, active, url）"""
    body = await request.json()
    allowed = {"title", "workspace", "init_script", "proxy", "tg_token", "tg_chat_id", "tg_enable", "active", "url"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    conn = get_db()
    try:
        with conn.cursor() as c:
            # Handle updated_at separately with raw SQL
            has_updated_at = "updated_at" in updates
            if has_updated_at:
                del updates["updated_at"]
            set_clause = ", ".join(f"{k}=%s" for k in updates)
            if has_updated_at:
                set_clause += ", updated_at=NOW()"
            c.execute(
                f"UPDATE ttyd_config SET {set_clause} WHERE pane_id=%s",
                list(updates.values()) + [pane_id]
            )
            if c.rowcount == 0:
                raise HTTPException(status_code=404, detail="pane_id not found")
            conn.commit()
            return format_response({"success": True, "pane_id": pane_id, "updated": updates}, request)
    finally:
        conn.close()
