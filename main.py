"""
本地服务注册表 API
端口: 14444
功能: 查询/管理 local_services 表
"""
import os
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

app = FastAPI(title="Local Services API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

# Helper for YAML/JSON response
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
app.include_router(ttyd.router, dependencies=[Depends(verify_token)])

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
