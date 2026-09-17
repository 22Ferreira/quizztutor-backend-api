"""
Provedor Google Gemini.
API nativa do Gemini (não é compatível com OpenAI diretamente).
Gratuito com limites generosos: 15 req/min, ~1M tokens/dia.

Obter chave grátis: https://aistudio.google.com
"""
import logging
import os

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from app.ai.providers.base import BaseLLMProvider, LLMMessage, LLMResponse
from app.ai.providers.openai_compat import get_http_client


logger = logging.getLogger(__name__)

GEMINI_CHAT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _is_retryable(exc: BaseException) -> bool:
    # Só vale a pena tentar de novo em falha PASSAGEIRA (rede, erro 5xx do
    # servidor). Retentar um 429 (limite de uso estourado) ou 404 (modelo
    # errado) na hora é inútil — vai falhar de novo do mesmo jeito e só
    # desperdiça mais uma tentativa contra a cota já esgotada.
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class GeminiProvider(BaseLLMProvider):
    """Provedor Google Gemini via REST API."""

    def _get_api_key(self) -> str | None:
        env_var = self.config.get("api_key_env", "GEMINI_API_KEY")
        return os.environ.get(env_var, "")

    def _get_model(self) -> str:
        return self.config.get("models", {}).get("default", "gemini-3.6-flash")

    # Sem isso, uma falha passageira (blip de rede, erro 5xx momentâneo) já
    # derrubava o Gemini na primeira tentativa — o provedor OpenAI-compatible
    # (Groq/OpenRouter) já tinha essa mesma proteção, o Gemini não. Fica
    # isolado numa função própria (que precisa RAISAR o erro, não devolver
    # um resultado) porque é assim que o @retry consegue interceptar e
    # tentar de novo — devolver um LLMResponse aqui dentro faria o @retry
    # nunca disparar.
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=3),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def _post(self, url: str, payload: dict, params_url: dict, timeout: float) -> dict:
        client = get_http_client()
        r = await client.post(url, json=payload, params=params_url, timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        api_key = self._get_api_key()
        if not api_key:
            return LLMResponse(content="", provider=self.name, model="", success=False, error="No API key")

        model = self._get_model()
        params = self._get_params(**kwargs)
        timeout = self.config.get("timeout_seconds", 45)

        # Separar system message das demais
        system_instruction = None
        chat_messages = []
        for m in messages:
            if m.role == "system":
                system_instruction = m.content
            else:
                role = "user" if m.role == "user" else "model"
                chat_messages.append({"role": role, "parts": [{"text": m.content}]})

        payload: dict = {
            "contents": chat_messages,
            "generationConfig": {
                "temperature": params.get("temperature", 0.3),
                "maxOutputTokens": params.get("max_tokens", 1024),
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        url = GEMINI_CHAT_URL.format(model=model)
        params_url = {"key": api_key}

        try:
            data = await self._post(url, payload, params_url, timeout)
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            return LLMResponse(content=content, provider=self.name, model=model, success=True)
        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            logger.warning(f"[Gemini] HTTP {e.response.status_code}: {body}")
            return LLMResponse(content="", provider=self.name, model=model, success=False, error=body)
        except Exception as e:
            logger.warning(f"[Gemini] Error: {e}")
            return LLMResponse(content="", provider=self.name, model=model, success=False, error=str(e))
