import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import settings

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
async def chat_completion(messages: list[dict]) -> str:
    url = f"{settings.TUTOR_BASE_URL.rstrip('/')}/v1/chat/completions"
    headers = {}
    if settings.TUTOR_API_KEY:
        headers["Authorization"] = f"Bearer {settings.TUTOR_API_KEY}"
    payload = {"model": settings.TUTOR_MODEL, "messages": messages, "temperature": 0.2}
    timeout = settings.TUTOR_TIMEOUT_SECONDS
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
