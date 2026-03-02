"""VNC 相关 API"""
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import subprocess
import httpx
import os
import json as _json
import re

router = APIRouter(prefix="/api/vnc", tags=["vnc"])

# --- 权限 helpers (同 tmux router 模式) ---
def _get_token_perms(request: Request) -> list:
    from routers.auth import _verify_token_from_db
    auth = request.headers.get('Authorization', '')
    token = auth[7:] if auth.startswith('Bearer ') else request.query_params.get('token', '')
    if not token:
        return []
    for path in ["/home/w3c_offical/global.json", os.path.expanduser("~/global.json")]:
        try:
            with open(path) as f:
                if _json.load(f).get("api_token") == token:
                    return ["api_full", "ttyd_read", "ttyd_write", "prompt", "pane_manage", "app_manage", "agent_manage", "desktop_manage", "vnc_read", "vnc_manage", "voice_to_text"]
        except Exception:
            pass
    result = _verify_token_from_db(token)
    return result.get("perms", []) if result and result.get("valid") else []

def _require_perm(request: Request, perm: str):
    perms = _get_token_perms(request)
    if perm not in perms and "api_full" not in perms:
        raise HTTPException(403, f"Requires {perm} permission")

# --- Models ---
class TypeBody(BaseModel):
    text: str
    target: str

class KeyBody(BaseModel):
    key: str
    display: str = ":1"

class CorrectBody(BaseModel):
    text: str

HOST_IP = os.getenv("VNC_HOST_IP", "127.0.0.1")

# --- 端点 ---

@router.post("/type")
async def vnc_type(body: TypeBody, request: Request):
    """通过 measure_window proxy 输入文本"""
    _require_perm(request, "vnc_manage")
    if not body.text.strip():
        raise HTTPException(400, "empty text")
    # :1 → 13431, :2 → 13432
    display_num = int(body.target.split(":")[1]) if ":" in body.target else 1
    proxy_port = 13430 + display_num
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            r = await client.post(f"http://{HOST_IP}:{proxy_port}/api/type", json={"text": body.text, "target": body.target})
            data = r.json()
            if not data.get("success"):
                raise HTTPException(500, data.get("error", "proxy error"))
        return {"success": True}
    except httpx.HTTPError as e:
        raise HTTPException(502, str(e))

@router.post("/proxy-type")
async def vnc_proxy_type(body: TypeBody, request: Request):
    """通过 xdotool 直接输入文本"""
    _require_perm(request, "vnc_manage")
    if not body.text.strip():
        raise HTTPException(400, "empty text")
    target = body.target
    # 安全检查 display 格式
    if not re.match(r'^:\d+$', target):
        raise HTTPException(400, "invalid display format")
    text_escaped = body.text.replace('"', '\\"')
    try:
        subprocess.run(f'DISPLAY={target} xdotool type -- "{text_escaped}"', shell=True, timeout=5, check=True, capture_output=True)
        subprocess.run(f'DISPLAY={target} xdotool key Return', shell=True, timeout=5, check=True, capture_output=True)
        return {"success": True}
    except subprocess.SubprocessError as e:
        raise HTTPException(500, str(e))

@router.post("/key")
async def vnc_key(body: KeyBody, request: Request):
    """发送按键"""
    _require_perm(request, "vnc_manage")
    if not re.match(r'^:\d+$', body.display):
        raise HTTPException(400, "invalid display format")
    # 安全检查 key 格式 (只允许字母数字和常见按键名)
    if not re.match(r'^[\w+\- ]+$', body.key):
        raise HTTPException(400, "invalid key format")
    try:
        subprocess.run(f'DISPLAY={body.display} xdotool key -- {body.key}', shell=True, timeout=5, check=True, capture_output=True)
        return {"success": True}
    except subprocess.SubprocessError as e:
        raise HTTPException(500, str(e))

@router.post("/voice")
async def vnc_voice(request: Request, file: UploadFile = File(...)):
    """语音转文字 — 代理到 voice_to_text 服务"""
    _require_perm(request, "voice_to_text")
    try:
        audio_data = await file.read()
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            r = await client.post("http://127.0.0.1:15001/voice_to_text",
                files={"file": ("audio.webm", audio_data, "audio/webm")})
            return r.json()
    except Exception as e:
        raise HTTPException(502, str(e))

@router.post("/correctEnglish")
async def vnc_correct_english(body: CorrectBody, request: Request):
    """英文纠错"""
    _require_perm(request, "vnc_manage")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty text")

    # 简单规则纠错 fallback
    def _fallback(t: str) -> str:
        import re as _re
        t = _re.sub(r'\br\s+you\b', 'are you', t, flags=_re.I)
        t = _re.sub(r'\bhow old a you\b', 'how old are you', t, flags=_re.I)
        t = _re.sub(r'\bi want test\b', 'I want to test', t, flags=_re.I)
        t = _re.sub(r'\bthis is work\b', 'this works', t, flags=_re.I)
        t = _re.sub(r'\biam\b', 'I am', t, flags=_re.I)
        t = _re.sub(r'\bu\b', 'you', t, flags=_re.I)
        t = _re.sub(r'\br\b', 'are', t, flags=_re.I)
        if t and t[0].islower():
            t = t[0].upper() + t[1:]
        if t and t[-1] not in '.!?':
            t += '.'
        return t.strip()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post("https://api-inference.huggingface.co/models/facebook/bart-large-cnn",
                json={"inputs": f"Correct this English text: {text}", "parameters": {"max_length": 200, "min_length": 10}})
            if r.status_code != 200:
                return {"success": True, "correctedText": _fallback(text)}
            result = r.json()
            corrected = result[0].get("summary_text") or result[0].get("generated_text") or text
            corrected = re.sub(r'^Correct this English text:\s*', '', corrected, flags=re.I).strip().strip("\"'")
            return {"success": True, "correctedText": corrected}
    except Exception:
        return {"success": True, "correctedText": _fallback(text)}
