"""Cloudflare AI Service — 统一调用入口"""
import httpx, os, json

_GLOBAL_JSON = "/home/w3c_offical/global.json"

def _creds():
    try:
        with open(_GLOBAL_JSON) as f:
            d = json.load(f)
            return d["CLOUDFLARE_ACCOUNT_ID_CICYBOT"], d["CLOUDFLARE_API_TOKEN_CICYBOT"]
    except Exception:
        return os.getenv("CF_ACCOUNT_ID", ""), os.getenv("CF_AI_TOKEN", "")

def _base():
    return f"https://api.cloudflare.com/client/v4/accounts/{_creds()[0]}/ai"

def _headers():
    return {"Authorization": f"Bearer {_creds()[1]}", "Content-Type": "application/json"}

async def run_model(model: str, input_data, **kwargs) -> dict:
    """通用模型调用"""
    payload = {"model": model, "input": input_data, **kwargs}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{_base()}/v1/responses", headers=_headers(), json=payload)
        return r.json()

async def run_model_raw(model: str, input_data, **kwargs) -> httpx.Response:
    """返回原始 response（用于 TTS 等二进制输出）"""
    payload = {"model": model, "input": input_data, **kwargs}
    async with httpx.AsyncClient(timeout=30) as c:
        return await c.post(f"{_base()}/v1/responses", headers=_headers(), json=payload)

def extract_text(data: dict) -> str | None:
    """从 AI response 中提取文本"""
    for item in data.get("output", []):
        if item.get("type") == "message":
            return item["content"][0]["text"]
    return None

async def ask(prompt: str, model: str = "@cf/openai/gpt-oss-120b") -> dict:
    return await run_model(model, prompt)

async def ask_text(prompt: str, model: str = "@cf/openai/gpt-oss-120b") -> str | None:
    """直接返回文本"""
    return extract_text(await ask(prompt, model))

async def translate(text: str, target_lang: str = "English") -> str | None:
    prompt = f"Translate the following text to {target_lang}. Only return the translated text, no explanations:\n{text}"
    return await ask_text(prompt, "@cf/meta/llama-3.1-70b-instruct")

async def correct_english(text: str) -> str | None:
    return await ask_text(f"Correct the following text to proper English. Only return the corrected text, no explanations:\n{text}")

async def usage(start: str, end: str) -> dict:
    """查询 AI 用量"""
    aid, token = _creds()
    query = """{ viewer { accounts(filter: {accountTag: "%s"}) {
        aiInferenceAdaptiveGroups(limit: 50, filter: {datetime_geq: "%s", datetime_leq: "%s"}, orderBy: [sum_totalNeurons_DESC]) {
            count sum { totalNeurons totalInputTokens totalOutputTokens } dimensions { modelId }
        }
    } } }""" % (aid, start, end)
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://api.cloudflare.com/client/v4/graphql",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"query": query})
        return r.json()
