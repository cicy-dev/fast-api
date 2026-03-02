"""Cloudflare AI API routes"""
from fastapi import APIRouter, Request
from fastapi.responses import Response
from services.cf_ai import ask, translate, correct_english, run_model_raw, extract_text, usage as cf_usage
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/cf", tags=["cf-ai"])

@router.post("/translate")
async def api_translate(request: Request):
    body = await request.json()
    text = await translate(body.get("input", ""))
    return {"text": text}

@router.post("/ask")
async def api_ask(request: Request):
    body = await request.json()
    data = await ask(body.get("input", ""))
    return data

@router.post("/tts")
async def api_tts(request: Request):
    body = await request.json()
    r = await run_model_raw("@cf/myshell/melotts", body.get("input", ""), lang=body.get("lang", "en"))
    return Response(content=r.content, media_type=r.headers.get("content-type", "audio/wav"))

@router.post("/stt")
async def api_stt(request: Request):
    from services.cf_ai import run_model
    body = await request.body()
    data = await run_model("@cf/openai/whisper", body)
    return data

@router.get("/usage")
async def api_usage(request: Request):
    now = datetime.utcnow()
    start = now.replace(day=1).strftime("%Y-%m-%dT00:00:00Z")
    end = (now + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    data = await cf_usage(start, end)
    groups = data.get("data", {}).get("viewer", {}).get("accounts", [{}])[0].get("aiInferenceAdaptiveGroups", [])
    return {
        "period": {"start": start, "end": end},
        "total": {
            "neurons": round(sum(g["sum"]["totalNeurons"] for g in groups), 2),
            "inputTokens": sum(g["sum"]["totalInputTokens"] for g in groups),
            "outputTokens": sum(g["sum"]["totalOutputTokens"] for g in groups),
            "requests": sum(g["count"] for g in groups),
        },
        "models": [{"model": g["dimensions"]["modelId"], "neurons": round(g["sum"]["totalNeurons"], 2), "inputTokens": g["sum"]["totalInputTokens"], "outputTokens": g["sum"]["totalOutputTokens"], "requests": g["count"]} for g in groups]
    }

@router.post("/chat")
async def api_chat(request: Request):
    """多轮对话接口"""
    import httpx, json
    body = await request.json()
    messages = body.get("messages", [])
    if not messages:
        messages = [{"role": "user", "content": body.get("input", "")}]
    with open("/home/w3c_offical/global.json") as f:
        d = json.load(f)
    aid, token = d["CLOUDFLARE_ACCOUNT_ID_CICYBOT"], d["CLOUDFLARE_API_TOKEN_CICYBOT"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{aid}/ai/v1/chat/completions"
    async with httpx.AsyncClient(timeout=60, proxy=None) as c:
        r = await c.post(url, headers={"Authorization": f"Bearer {token}"},
            json={"model": body.get("model", "@cf/meta/llama-3.1-8b-instruct"), "messages": messages})
        return r.json()

@router.post("/chat/stream")
async def api_chat_stream(request: Request):
    """流式对话接口"""
    import httpx, json
    from fastapi.responses import StreamingResponse
    body = await request.json()
    messages = body.get("messages", [])
    if not messages:
        messages = [{"role": "user", "content": body.get("input", "")}]
    with open("/home/w3c_offical/global.json") as f:
        d = json.load(f)
    aid, token = d["CLOUDFLARE_ACCOUNT_ID_CICYBOT"], d["CLOUDFLARE_API_TOKEN_CICYBOT"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{aid}/ai/v1/chat/completions"

    async def gen():
        async with httpx.AsyncClient(timeout=60, proxy=None) as c:
            async with c.stream("POST", url, headers={"Authorization": f"Bearer {token}"},
                json={"model": body.get("model", "@cf/meta/llama-3.1-8b-instruct"), "messages": messages, "stream": True}) as r:
                async for line in r.aiter_lines():
                    if line.startswith("data: "):
                        yield line + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
