"""
本地服务注册表 API
端口: 14444
功能: 查询/管理 local_services 表
"""
import os
import sys
import logging
from dotenv import load_dotenv
load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
if "--reload" in sys.argv:
    LOG_LEVEL = "DEBUG"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# Set all loggers
for name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
    log = logging.getLogger(name)
    log.setLevel(getattr(logging, LOG_LEVEL))
logger = logging.getLogger(__name__)

import json
import yaml
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import Optional

# Import routers
from routers.tmux import router as tmux_router
# from routers import ttyd
from routers import groups as groups_module
from routers import apps as apps_module
from routers import auth as auth_module
from routers import websocket_agent
from routers import board as board_module
from routers import workers as workers_module
from routers import dashboard as dashboard_module
from routers import vnc as vnc_module
from routers import agents as agents_module

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as StarletteJSONResponse

app = FastAPI(title="Local Services API", version="1.0")

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "https://g-vnc.cicy.de5.net,https://g-fast-api.cicy.de5.net,http://localhost,http://127.0.0.1").split(",") if o.strip()]

class CORSErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as e:
            response = StarletteJSONResponse({"detail": str(e)}, status_code=500)
        origin = request.headers.get("origin", "")
        if origin:
            response.headers["access-control-allow-origin"] = origin
            response.headers["access-control-allow-credentials"] = "true"
        return response

app.add_middleware(CORSErrorMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_origin_regex=r"https?://.*", allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

# Helper for YAML/JSON response (default: JSON; optional: Accept: application/yaml)
def is_yaml(request: Request) -> bool:
    return "application/yaml" in request.headers.get("accept", "").lower()

def format_response(data: dict, request: Request = None):
    if request and is_yaml(request):
        yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return PlainTextResponse(yaml_str, media_type="application/yaml")
    return data

# Load token from global.json
def load_token():
    # Check mounted location first (for docker running as non-root)
    global_json = "/home/w3c_offical/global.json"
    if not os.path.exists(global_json):
        global_json = os.path.expanduser("~/global.json")
    
    # Generate if not exists
    if not os.path.exists(global_json):
        import secrets
        token = secrets.token_hex(32)
        data = {"api_token": token}
        os.makedirs(os.path.dirname(global_json), exist_ok=True)
        with open(global_json, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Generated new token in {global_json}")
        return token
    
    # Load existing
    try:
        with open(global_json) as f:
            data = json.load(f)
            return data.get("api_token", "")
    except:
        return ""

AUTH_TOKEN = load_token()
security = HTTPBearer()

def verify_token(cred: HTTPAuthorizationCredentials = Depends(security)):
    token = cred.credentials
    # 先检查管理员 token
    if token == AUTH_TOKEN:
        return token
    # 再检查数据库 token
    from routers.auth import _verify_token_from_db
    token_info = _verify_token_from_db(token)
    if token_info and token_info.get("valid"):
        return token
    raise HTTPException(status_code=401, detail="invalid token")

# Include routers with authentication
app.include_router(tmux_router, dependencies=[Depends(verify_token)])
# app.include_router(ttyd.router)  # Deprecated: moved to /api/tmux/ttyd/*
app.include_router(groups_module.router, dependencies=[Depends(verify_token)])
app.include_router(apps_module.router, dependencies=[Depends(verify_token)])
app.include_router(auth_module.router)  # Auth endpoints don't need token verification
app.include_router(websocket_agent.router)  # WebSocket endpoints
app.include_router(board_module.router, dependencies=[Depends(verify_token)])  # Board API
app.include_router(workers_module.router, dependencies=[Depends(verify_token)])  # Worker communication
app.include_router(dashboard_module.router, dependencies=[Depends(verify_token)])  # Dashboard API (checks api_full internally)
app.include_router(vnc_module.router, dependencies=[Depends(verify_token)])  # VNC API
app.include_router(agents_module.router, dependencies=[Depends(verify_token)])  # Agents API
from routers import cf_ai as cf_ai_module
app.include_router(cf_ai_module.router, dependencies=[Depends(verify_token)])  # Cloudflare AI proxy
from routers import settings as settings_module
app.include_router(settings_module.router, dependencies=[Depends(verify_token)])  # Settings API
from routers import utils as utils_module
app.include_router(utils_module.router, dependencies=[Depends(verify_token)])  # Utils API

from db_pool import get_db as get_pool_db

def get_db():
    """Get database connection from pool"""
    return get_pool_db()

@app.get("/api/qa/{record_id}")
def qa_detail(record_id: int, token: str = Depends(verify_token)):
    with get_pool_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT * FROM llm_qa_history WHERE id=%s", (record_id,))
            row = c.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="not found")
            row["created_at"] = str(row.get("created_at", ""))
            row["updated_at"] = str(row.get("updated_at", ""))
            return row

@app.on_event("startup")
async def startup_event():
    """Start all tmux sessions and ttyd services from database config on startup"""
    import socket
    import time
    from routers.tmux.router import create_ttyd_pane_common, run_tmux

    # Wait for MySQL/Redis to be ready (infinite retry)
    retry_delay = 2
    attempt = 0
    while True:
        attempt += 1
        try:
            conn = get_pool_db()
            conn.close()
            logger.info(f"✓ MySQL connected (attempt {attempt})")
            break
        except Exception as e:
            logger.warning(f"MySQL not ready (attempt {attempt}): {e}")
            time.sleep(retry_delay)

    # 迁移: 添加 common_prompt 列
    try:
        conn = get_pool_db()
        with conn.cursor() as c:
            c.execute("""
                ALTER TABLE ttyd_config 
                ADD COLUMN common_prompt LONGTEXT DEFAULT NULL
            """)
        conn.commit()
        logger.info("✓ 成功添加 common_prompt 列")
    except Exception as e:
        if "Duplicate column" in str(e):
            logger.info("✓ common_prompt 列已存在")
        else:
            logger.warning(f"迁移失败: {e}")

    def is_port_listening(port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result == 0

    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT pane_id, title, ttyd_port, workspace, init_script, config, tg_token, tg_chat_id, tg_enable, active, agent_type FROM ttyd_config WHERE active=1")
            configs = c.fetchall()
        
        print(f"[Startup] Found {len(configs)} active pane configs in database")
        
        for config in configs:
            pane_id = config["pane_id"]
            port = int(config["ttyd_port"])
            
            if is_port_listening(port):
                print(f"[Startup] ttyd already running on port {port} for {pane_id}")
                continue
            
            parts = pane_id.split(":")
            if len(parts) < 2:
                print(f"[Startup] Invalid pane_id format: {pane_id}")
                continue
            
            session_name = parts[0]
            window_part = parts[1]
            window_name = window_part.split(".")[0] if "." in window_part else window_part
            
            # Check if session exists using common function
            session_exists = run_tmux(["has-session", "-t", session_name], check_session=True)
            if session_exists is None:
                workspace_expanded = os.path.expanduser(config.get("workspace") or "~")
                print(f"[Startup] Creating tmux session {session_name} with workspace {workspace_expanded}")
                run_tmux(["new-session", "-d", "-s", session_name, "-n", window_name, "-c", workspace_expanded])
            
            # Parse config JSON to get proxy
            import json
            config_data = {}
            if config.get("config"):
                try:
                    config_data = json.loads(config["config"])
                except:
                    pass
            proxy = config_data.get("proxy", "")
            
            # Reuse create_ttyd_pane_common
            try:
                print(f"[Startup] Starting ttyd for {pane_id}")
                create_ttyd_pane_common(
                    pane_id=pane_id,
                    session_name=session_name,
                    win_name=window_name,
                    ttyd_port=port,
                    workspace=config.get("workspace"),
                    init_script=config.get("init_script") or "",
                    proxy=proxy,
                    title=config.get("title", pane_id),
                    tg_token=config.get("tg_token"),
                    tg_chat_id=config.get("tg_chat_id"),
                    tg_enable=config.get("tg_enable", False),
                    clear_after_init=False,
                    no_insert_db=True,
                    agent_type=config.get("agent_type")
                )
                print(f"[Startup] Started ttyd on port {port} for {pane_id}")
            except Exception as e:
                print(f"[Startup] Failed to start {pane_id}: {e}")
        
        print("[Startup] Finished starting all services")

@app.get("/api/health")
async def api_health(request: Request):
    return format_response({"status": "ok", "source": "fast-api"}, request)

@app.get("/health")
async def health(request: Request):
    return format_response({"status": "ok"}, request)

@app.get("/api/auth/verify")
async def verify_auth(request: Request, token: str = Depends(verify_token)):
    from routers.auth import _verify_token_from_db
    token_info = _verify_token_from_db(token)
    if token_info and token_info.get("valid"):
        return format_response({
            "valid": True,
            "token": token[:8] + "...",
            "perms": token_info.get("perms", []),
            "group_id": token_info.get("group_id"),
            "note": token_info.get("note")
        }, request)
    # Fallback: 超级管理员 token (global.json)
    if token == AUTH_TOKEN:
        return format_response({
            "valid": True,
            "token": token[:8] + "...",
            "perms": ["api_full", "ttyd_read", "ttyd_write", "prompt", "pane_manage", "app_manage", "agent_manage", "desktop_manage"],
            "group_id": None
        }, request)
    return format_response({"valid": True, "token": token[:8] + "..."}, request)


@app.get("/ping")
async def ping(request: Request):
    from datetime import datetime
    return format_response({
        "pong": "ok",
        "version": "1.0",
        "server_datetime": datetime.now().isoformat()
    }, request)

@app.get("/api/services")
def list_services(request: Request, token: str = Depends(verify_token)):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT id,port,name,description,url,path,status,created_at,updated_at FROM local_services ORDER BY port")
            return format_response({"services": c.fetchall()}, request)
    finally:
        conn.close()

@app.get("/api/services/{port}")
def get_service(port: int, request: Request, token: str = Depends(verify_token)):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT * FROM local_services WHERE port=%s", (port,))
            row = c.fetchone()
            return format_response(row or {"error": "not found"}, request)
    finally:
        conn.close()

class ServiceIn(BaseModel):
    port: int
    name: str
    description: str = ""
    url: str = ""
    path: str = ""
    status: str = "unknown"

@app.post("/api/services")
def upsert_service(s: ServiceIn, request: Request, token: str = Depends(verify_token)):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("""INSERT INTO local_services (port,name,description,url,path,status)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE name=VALUES(name),description=VALUES(description),
                url=VALUES(url),path=VALUES(path),status=VALUES(status)""",
                (s.port, s.name, s.description, s.url, s.path, s.status))
        conn.commit()
        return format_response({"success": True}, request)
    finally:
        conn.close()

@app.delete("/api/services/{port}")
def delete_service(port: int, request: Request, token: str = Depends(verify_token)):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM local_services WHERE port=%s", (port,))
        conn.commit()
        return format_response({"success": True}, request)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migrated from ttyd-proxy-v1 server/src/index.ts
# ---------------------------------------------------------------------------

import subprocess as _subprocess
import re as _re
import requests as _requests
from routers.tmux.router import run_tmux


@app.post("/api/tmux")
async def tmux_send(request: Request, token: str = Depends(verify_token)):
    """Send text to tmux pane (compat with old server endpoint).
    Body: {"text": "...", "target": "session:window.pane"}
    """
    body = await request.json()
    text = body.get("text", "")
    target = body.get("target", "")
    if not target:
        return format_response({"success": False, "error": "target required"}, request)
    if text:
        run_tmux(["send-keys", "-t", target, text, "Enter"])
    return format_response({"success": True}, request)


@app.get("/api/bots")
def get_bots(request: Request, token: str = Depends(verify_token)):
    """Load bot list via docker exec tts-bot."""
    try:
        out = _subprocess.check_output(
            ["docker", "exec", "tts-bot", "python3", "/tmp/load_bots.py"],
            timeout=8, stderr=_subprocess.DEVNULL
        ).decode().strip()
        return format_response(json.loads(out), request)
    except Exception as e:
        return format_response({"error": str(e), "bots": []}, request)


@app.get("/api/tmux-list")
def tmux_list(request: Request, token: str = Depends(verify_token)):
    """Return tree view of tmux sessions/windows/panes (mirrors ~/tools/tre logic)."""
    try:
        sessions_out = run_tmux(["list-sessions", "-F", "#{session_name}"])
        sessions = [s for s in sessions_out.strip().split("\n") if s]
    except Exception:
        return format_response({"success": True, "output": "没有运行中的 session"}, request)

    lines = []
    for i, s in enumerate(sessions):
        ls = i == len(sessions) - 1
        lines.append(f"{'└──' if ls else '├──'} {s}")
        try:
            wo = run_tmux(["list-windows", "-t", s, "-F", "#{window_index} #{window_name}"])
            ws = [w for w in wo.strip().split("\n") if w]
        except Exception:
            ws = []
        for j, w in enumerate(ws):
            parts = w.split(None, 1)
            if len(parts) < 2:
                continue
            lw = j == len(ws) - 1
            ind = "    " if ls else "│   "
            lines.append(f"{ind}{'└──' if lw else '├──'} {parts[0]} {parts[1]}")
            try:
                po = run_tmux(["list-panes", "-t", f"{s}:{parts[0]}", "-F", "#{pane_index}"])
                ps = [x for x in po.strip().split("\n") if x]
            except Exception:
                ps = []
            for k, pn in enumerate(ps):
                lp = k == len(ps) - 1
                pi = "    " if lw else "│   "
                lines.append(f"{ind}{pi}{'└──' if lp else '├──'} {s}:{parts[1]}.{pn}")

    return format_response({"success": True, "output": "\n".join(lines)}, request)


def _fallback_correct(text: str) -> str:
    text = _re.sub(r'\br\s+you\b', 'are you', text, flags=_re.IGNORECASE)
    text = _re.sub(r'\bhow old a you\b', 'how old are you', text, flags=_re.IGNORECASE)
    text = _re.sub(r'\bu\b', 'you', text, flags=_re.IGNORECASE)
    text = _re.sub(r'\br\b', 'are', text, flags=_re.IGNORECASE)
    return text[0].upper() + text[1:] if text else text


@app.post("/api/correctEnglish")
async def correct_english_api(request: Request, token: str = Depends(verify_token)):
    """Correct English text (English only)."""
    import httpx, json
    body = await request.json()
    text = body.get("text", "")
    if not text:
        return format_response({"success": False, "error": "no text"}, request)
    
    try:
        # Use chat API with system prompt
        with open("/home/w3c_offical/global.json") as f:
            d = json.load(f)
        aid, token_cf = d["CLOUDFLARE_ACCOUNT_ID_CICYBOT"], d["CLOUDFLARE_API_TOKEN_CICYBOT"]
        url = f"https://api.cloudflare.com/client/v4/accounts/{aid}/ai/v1/chat/completions"
        
        messages = [
            {"role": "system", "content": "You are an English grammar corrector with Chinese pinyin understanding. Your tasks:\n1. Correct English spelling and grammar errors\n2. Convert Chinese pinyin to appropriate English translations based on context\n3. Keep the natural flow and meaning of the sentence\n4. Output format: First line is corrected English, second line is Chinese translation\n5. Use newline to separate English and Chinese\n\nExamples:\n- Input: 'nihao how r u'\n  Output: 'Hello, how are you?\\n你好,你好吗?'\n- Input: 'hai shi buxing'\n  Output: 'Still not working\\n还是不行'"},
            {"role": "user", "content": text}
        ]
        
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, headers={"Authorization": f"Bearer {token_cf}"},
                json={"model": "@cf/openai/gpt-oss-120b", "messages": messages})
            result = r.json()
            corrected = result["choices"][0]["message"]["content"].strip()
            # Split into English and Chinese
            lines = corrected.split('\n', 1)
            if len(lines) == 2:
                return format_response({"success": True, "result": lines}, request)
            else:
                return format_response({"success": True, "result": [corrected, ""]}, request)
    except Exception as e:
        return format_response({"success": False, "error": str(e)}, request)

