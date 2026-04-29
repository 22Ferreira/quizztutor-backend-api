"""
Provedor Hugging Face Inference API.
Gratuito com token do HuggingFace: https://huggingface.co/settings/tokens
Mais lento que Groq/Gemini, mas funciona como fallback.
"""
import logging
import os

import httpx

from app.ai.providers.base import BaseLLMProvider, LLMMessage, LLMResponse
from app.ai.providers.openai_compat import get_http_client

logger = logging.getLogger(__name__)


class HuggingFaceProvider(BaseLLMProvider):
    """Provedor Hugging Face Inference API."""

    def _get_token(self) -> str | None:
        env_var = self.config.get("api_key_env", "HF_TOKEN")
        return os.environ.get(env_var, "")

    def _get_model(self) -> str:
        return self.config.get("models", {}).get("default", "mistralai/Mistral-7B-Instruct-v0.1")

    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        token = self._get_token()
        model = self._get_model()
        params = self._get_params(**kwargs)
        timeout = self.config.get("timeout_seconds", 60)

        # Converter mensagens para formato texto simples (instruction format)
        prompt_parts = []
        for m in messages:
            if m.role == "system":
                prompt_parts.append(f"[INST] <<SYS>>\n{m.content}\n<</SYS>>\n")
            elif m.role == "user":
                prompt_parts.append(f"{m.content} [/INST]")
            else:
                prompt_parts.append(m.content)
        prompt = "\n".join(prompt_parts)

        url = f"https://api-inference.huggingface.co/models/{model}"
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = {
            "inputs": prompt,
            "parameters": {
                "temperature": params.get("temperature", 0.3),
                "max_new_tokens": params.get("max_new_tokens", 512),
                "return_full_text": False,
            },
        }

        try:
            client = get_http_client()
            r = await client.post(url, json=payload, headers=headers, timeout=timeout)
            if r.status_code == 503:
                return LLMResponse(content="", provider=self.name, model=model, success=False, error="Model loading")
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and data:
                content = data[0].get("generated_text", "")
            else:
                content = str(data)
            return LLMResponse(content=content.strip(), provider=self.name, model=model, success=True)
        except Exception as e:
            logger.warning(f"[HuggingFace] Error: {e}")
            return LLMResponse(content="", provider=self.name, model=model, success=False, error=str(e))
