"""
Provedor Google Gemini.
API nativa do Gemini (não é compatível com OpenAI diretamente).
Gratuito com limites generosos: 15 req/min, ~1M tokens/dia.

Obter chave grátis: https://aistudio.google.com
"""
import logging
import os

import httpx

from app.ai.providers.base import BaseLLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)

GEMINI_CHAT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider(BaseLLMProvider):
    """Provedor Google Gemini via REST API."""

    def _get_api_key(self) -> str | None:
        env_var = self.config.get("api_key_env", "GEMINI_API_KEY")
        return os.environ.get(env_var, "")

    def _get_model(self) -> str:
        return self.config.get("models", {}).get("default", "gemini-1.5-flash")

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
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, json=payload, params=params_url)
                r.raise_for_status()
                data = r.json()
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                return LLMResponse(content=content, provider=self.name, model=model, success=True)
        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            logger.warning(f"[Gemini] HTTP {e.response.status_code}: {body}")
            return LLMResponse(content="", provider=self.name, model=model, success=False, error=body)
        except Exception as e:
            logger.warning(f"[Gemini] Error: {e}")
            return LLMResponse(content="", provider=self.name, model=model, success=False, error=str(e))
