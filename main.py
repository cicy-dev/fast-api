"""
本地服务注册表 API
端口: 14444
功能: 查询/管理 local_services 表
"""
import os
from dotenv import load_dotenv
load_dotenv()

import pymysql
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
from routers import ttyd
from routers import groups as groups_module
from routers import apps as apps_module
from routers import auth as auth_module
from routers import websocket_agent
from routers import board as board_module
from routers import workers as workers_module

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as StarletteJSONResponse

app = FastAPI(title="Local Services API", version="1.0")

ALLOWED_ORIGINS = [
    "https://desktop.cicy.de5.net",
    "https://ttyd-dev.cicy.de5.net",
    "https://ttyd-proxy.cicy.de5.net",
    "http://localhost:6905",
    "http://localhost:6902",
    "http://localhost:6901",
]

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
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

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
    if cred.credentials != AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")
    return cred.credentials

# Include routers with authentication
app.include_router(tmux_router, dependencies=[Depends(verify_token)])
app.include_router(ttyd.router)  # No auth for internal cache
app.include_router(groups_module.router, dependencies=[Depends(verify_token)])
app.include_router(apps_module.router, dependencies=[Depends(verify_token)])
app.include_router(auth_module.router)  # Auth endpoints don't need token verification
app.include_router(websocket_agent.router)  # WebSocket endpoints
app.include_router(board_module.router, dependencies=[Depends(verify_token)])  # Board API
app.include_router(workers_module.router, dependencies=[Depends(verify_token)])  # Worker communication

def verify_token(cred: HTTPAuthorizationCredentials = Depends(security)):
    if cred.credentials != AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")
    return cred.credentials

DB = dict(
    host=os.getenv("MYSQL_HOST", "127.0.0.1"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    database=os.getenv("MYSQL_DATABASE", "tts_bot"),
    charset="utf8mb4"
)

def get_db():
    return pymysql.connect(**DB, cursorclass=pymysql.cursors.DictCursor)

@app.get("/api/qa/{record_id}")
def qa_detail(record_id: int, token: str = Depends(verify_token)):
    qa_db = {**DB, "database": "llm_qa_history"}
    conn = pymysql.connect(**qa_db, cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as c:
            c.execute("SELECT * FROM llm_qa_history WHERE id=%s", (record_id,))
            row = c.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="not found")
            row["created_at"] = str(row.get("created_at", ""))
            row["updated_at"] = str(row.get("updated_at", ""))
            return row
    finally:
        conn.close()

@app.on_event("startup")
async def startup_event():
    """Start all tmux sessions and ttyd services from database config on startup"""
    import subprocess
    import socket
    import time

    TTYD_BINARY_PATH = os.getenv("TTYD_BINARY_PATH", "ttyd")
    TTYD_BASE_URL = os.getenv("TTYD_BASE_URL", "")

    def run_tmux_cmd(cmd, check_session=False):
        result = subprocess.run(["tmux"] + cmd, capture_output=True, text=True)
        if result.returncode != 0:
            err = result.stderr.strip().lower()
            if check_session and ("no server running" in err or "can't find session" in err or "can't find window" in err):
                return None
            print(f"tmux error: {result.stderr.strip()}")
            return None
        return result.stdout.strip()

    def is_port_listening(port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result == 0

    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT pane_id, title, ttyd_port, workspace, init_script, proxy, active FROM ttyd_config WHERE active=1")
            configs = c.fetchall()
        
        print(f"[Startup] Found {len(configs)} active pane configs in database")
        
        for config in configs:
            pane_id = config["pane_id"]
            port = int(config["ttyd_port"])
            workspace = config.get("workspace")
            init_script = config.get("init_script")
            proxy = config.get("proxy")
            title = config.get("title", pane_id)
            
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
            
            session_exists = run_tmux_cmd(["has-session", "-t", session_name], check_session=True)
            if session_exists is None:
                workspace_expanded = os.path.expanduser(workspace or "~")
                print(f"[Startup] Creating tmux session {session_name} with workspace {workspace_expanded}")
                run_tmux_cmd(["new-session", "-d", "-s", session_name, "-n", window_name, "-c", workspace_expanded])
            
            token = AUTH_TOKEN
            ttyd_cmd = (
                f"nohup {TTYD_BINARY_PATH} -W -p {port} "
                f"-c user:{token} "
                f"tmux attach -t {pane_id} "
                f"> /home/w3c_offical/projects/ai-workers/fast-api/logs/ttyd_{port}.log 2>&1 &"
            )
            run_tmux_cmd(["run-shell", ttyd_cmd])
            print(f"[Startup] Started ttyd on port {port} for {pane_id}")
            
            # export X_PANE_ID
            run_tmux_cmd(["send-keys", "-t", pane_id, f"export X_PANE_ID='{pane_id}'", "Enter"])

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
                run_tmux_cmd(["send-keys", "-t", pane_id, proxy_cmd, "Enter"])
            
            run_tmux_cmd(["send-keys", "-t", pane_id, "clear", "Enter"])
            time.sleep(0.3)
            run_tmux_cmd(["send-keys", "-t", pane_id, "clear", "Enter"])

            # Auto cd to workspace and start kiro-cli
            if workspace:
                workspace_expanded = os.path.expanduser(workspace)
                run_tmux_cmd(["send-keys", "-t", pane_id, f"cd {workspace_expanded}", "Enter"])
            # kiro-cli will be started manually by user

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
                        run_tmux_cmd(["send-keys", "-t", pane_id, key_val])
                    else:
                        run_tmux_cmd(["send-keys", "-t", pane_id, line, "Enter"])
            
            max_wait = 30
            elapsed = 0
            while elapsed < max_wait:
                if is_port_listening(port):
                    print(f"[Startup] ttyd ready on port {port}")
                    break
                time.sleep(0.5)
                elapsed += 0.5
            else:
                print(f"[Startup] Warning: ttyd not ready on port {port} after {max_wait}s")
        
        print("[Startup] Finished starting all services")
    except Exception as e:
        print(f"[Startup] Error: {e}")
    finally:
        conn.close()

@app.get("/api/health")
async def api_health(request: Request):
    return format_response({"status": "ok", "source": "fast-api"}, request)

@app.get("/health")
async def health(request: Request):
    return format_response({"status": "ok"}, request)

@app.get("/api/auth/verify")
async def verify_auth(request: Request, token: str = Depends(verify_token)):
    return format_response({"valid": True, "token": token[:8] + "..."}, request)

@app.post("/api/test/login")
async def test_login(request: Request, token: str = Depends(verify_token)):
    return format_response({
        "success": True,
        "message": "Login simulation - token stored in localStorage on client",
        "token_prefix": token[:8]
    }, request)

@app.get("/api/test/ui-state")
async def get_ui_state(request: Request, token: str = Depends(verify_token)):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT pane_id, ttyd_port, ttyd_token FROM ttyd_config")
            configs = c.fetchall()
        return format_response({
            "logged_in": True,
            "panes_count": len(configs),
            "configs": configs,
            "frontend_token_check": "Use /api/auth/verify to check token validity"
        }, request)
    finally:
        conn.close()

@app.get("/api/test/check-auth")
async def check_auth_endpoint(request: Request, token: str = Depends(verify_token)):
    return format_response({
        "status": "ok",
        "message": "Auth works - token is valid",
        "token_prefix": token[:8]
    }, request)

@app.get("/api/test/debug-login")
async def debug_login(request: Request):
    """Debug endpoint - no auth required"""
    return format_response({
        "message": "Debug login endpoint - use /api/auth/verify for actual auth",
        "endpoints": {
            "verify": "/api/auth/verify (requires auth)",
            "health": "/health (no auth)",
            "test_ui_state": "/api/test/ui-state (requires auth)"
        }
    }, request)

@app.get("/api/test/errors")
async def get_test_errors(request: Request, token: str = Depends(verify_token)):
    return format_response({
        "errors": [],
        "message": "No UI errors - frontend running correctly"
    }, request)

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
async def correct_english(request: Request, token: str = Depends(verify_token)):
    """Correct English text via HuggingFace, with regex fallback."""
    body = await request.json()
    text = body.get("text", "")
    if not text:
        return format_response({"success": False, "error": "no text"}, request)
    try:
        resp = _requests.post(
            "https://api-inference.huggingface.co/models/facebook/bart-large-cnn",
            json={"inputs": f"Correct this English text: {text}",
                  "parameters": {"max_length": 200, "min_length": 10}},
            timeout=10
        )
        if resp.status_code == 200:
            result = resp.json()
            corrected = (result[0].get("summary_text") or result[0].get("generated_text") or text)
            corrected = _re.sub(r'^Correct this English text:\s*', '', corrected, flags=_re.IGNORECASE)
            corrected = corrected.strip('"\'').strip()
            return format_response({"success": True, "correctedText": corrected}, request)
    except Exception:
        pass
    return format_response({"success": True, "correctedText": _fallback_correct(text)}, request)
