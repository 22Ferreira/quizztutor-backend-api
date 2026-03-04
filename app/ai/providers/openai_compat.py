"""
Provedor genérico compatível com OpenAI.
Funciona com: Groq, OpenRouter, Ollama, OpenAI, Together, Anyscale, etc.
Qualquer API que segue o padrão /v1/chat/completions da OpenAI.
"""
import logging
import os
from tenacity import retry, stop_after_attempt, wait_exponential

import httpx

from app.ai.providers.base import BaseLLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)


class OpenAICompatProvider(BaseLLMProvider):
    """
    Provedor genérico para APIs compatíveis com OpenAI.
    Suporta: Groq, OpenRouter, Ollama, OpenAI, etc.
    """

    def _resolve_api_key(self) -> str | None:
        env_var = self.config.get("api_key_env")
        if not env_var:
            return None
        return os.environ.get(env_var, "")

    def _resolve_base_url(self) -> str:
        # Alguns provedores têm URL via env (ex: Ollama)
        url_env = self.config.get("base_url_env")
        if url_env:
            return os.environ.get(url_env, self.config.get("base_url_default", "http://localhost:11434"))
        return self.config.get("base_url", "")

    def _get_model(self) -> str:
        models = self.config.get("models", {})
        return models.get("default", "gpt-3.5-turbo")

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, min=0.5, max=3))
    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        base_url = self._resolve_base_url()
        api_key = self._resolve_api_key()
        model = self._get_model()
        params = self._get_params(**kwargs)
        timeout = self.config.get("timeout_seconds", 30)

        url = f"{base_url.rstrip('/')}/v1/chat/completions"

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Headers extras (ex: OpenRouter precisa de Referer)
        extra_headers = self.config.get("headers_extra", {})
        headers.update(extra_headers)

        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": params.get("temperature", 0.3),
            "max_tokens": params.get("max_tokens", 1024),
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                return LLMResponse(
                    content=content,
                    provider=self.name,
                    model=model,
                    success=True,
                )
        except httpx.HTTPStatusError as e:
            logger.warning(f"[{self.name}] HTTP error: {e.response.status_code} — {e.response.text[:200]}")
            return LLMResponse(content="", provider=self.name, model=model, success=False, error=str(e))
        except Exception as e:
            logger.warning(f"[{self.name}] Error: {e}")
            return LLMResponse(content="", provider=self.name, model=model, success=False, error=str(e))
