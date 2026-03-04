"""
Gerenciador de provedores LLM.
- Lê configurações do llm_providers.yaml
- Instancia os provedores ativos
- Executa com fallback automático na ordem configurada
- Aplica rate limiting e logging
"""
import logging
from app.config import settings
import os
from typing import TYPE_CHECKING

from app.ai.configs.loader import get_llm_providers
from app.ai.providers.base import BaseLLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)


def _build_provider(name: str, config: dict) -> BaseLLMProvider | None:
    """Instancia o provedor correto baseado na config."""
    if not config.get("enabled", False):
        return None

    # Verificar se tem API key configurada (exceto Ollama)
    api_key_env = config.get("api_key_env")
    if api_key_env:
        key_val = os.environ.get(api_key_env, "")
        if not key_val:
            logger.debug(f"Provider '{name}' skipped: env var '{api_key_env}' not set")
            return None

    if config.get("openai_compatible", True) and name not in ("google_gemini", "huggingface", "cohere"):
        from app.ai.providers.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(config)
    elif name == "google_gemini":
        from app.ai.providers.gemini import GeminiProvider
        return GeminiProvider(config)
    elif name == "huggingface":
        from app.ai.providers.huggingface import HuggingFaceProvider
        return HuggingFaceProvider(config)
    elif name == "ollama":
        # Ollama é OpenAI-compatible
        from app.ai.providers.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(config)
    else:
        logger.warning(f"Provider '{name}' has no implementation. Skipping.")
        return None


class LLMManager:
    """
    Gerenciador central de LLMs.
    Tenta provedores na ordem configurada, com fallback automático.
    """

    def __init__(self):
        self._providers: list[tuple[str, BaseLLMProvider]] = []
        self._config: dict = {}
        self._initialized = False

    def _ensure_initialized(self):
        if self._initialized:
            return
        self._load()

    def _load(self):
        """Carrega e instancia todos os provedores habilitados."""
        cfg = get_llm_providers()
        self._config = cfg

        fallback_order = cfg.get("fallback_order", [])
        providers_cfg = cfg.get("providers", {})

        # Se você quer usar APENAS 1 provedor por vez (mais simples no início),
        # configure no backend/.env:
        #   AI_PROVIDER=gemini | groq | openrouter | huggingface | ollama
        # Isso desliga o fallback automático e força um único provedor.
        forced = (settings.AI_PROVIDER or '').strip().lower()
        alias = {
            'gemini': 'google_gemini',
            'google_gemini': 'google_gemini',
            'hf': 'huggingface',
            'huggingface': 'huggingface',
        }
        if forced:
            forced_id = alias.get(forced, forced)
            if forced_id in providers_cfg:
                fallback_order = [forced_id]
                logger.info(f"AI_PROVIDER forcing enabled -> {forced_id}")
            else:
                logger.warning(f"AI_PROVIDER='{forced}' not found in llm_providers.yaml. Using normal fallback_order.")

        self._providers = []
        for name in fallback_order:
            pcfg = providers_cfg.get(name, {})
            provider = _build_provider(name, pcfg)
            if provider:
                self._providers.append((name, provider))
                logger.info(f"LLM provider ready: {name} ({pcfg.get('name', name)})")

        if not self._providers:
            logger.warning("No LLM providers configured! Tutor will use fallback messages only.")

        self._initialized = True

    def reload(self):
        """Recarrega config e provedores (útil para hot-reload)."""
        self._initialized = False
        from app.ai.configs.loader import reload_all
        reload_all()
        self._load()

    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """
        Envia para o primeiro provedor disponível.
        Em caso de falha, tenta o próximo (fallback).
        """
        self._ensure_initialized()

        global_cfg = self._config.get("global", {})
        auto_fallback = global_cfg.get("auto_fallback", True)
        fallback_message = global_cfg.get("fallback_message", "Serviço temporariamente indisponível.")

        if not self._providers:
            return LLMResponse(
                content=fallback_message,
                provider="none",
                model="none",
                success=False,
                error="No providers configured",
            )

        last_error = None
        for name, provider in self._providers:
            logger.debug(f"Trying LLM provider: {name}")
            try:
                response = await provider.chat(messages, **kwargs)
                if response.success and response.content:
                    logger.info(f"LLM response from: {name}")
                    if global_cfg.get("log_all_calls", False):
                        logger.debug(f"[{name}] Response preview: {response.content[:100]}")
                    return response
                else:
                    last_error = response.error
                    logger.warning(f"Provider '{name}' failed: {response.error}")
                    if not auto_fallback:
                        break
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Provider '{name}' exception: {e}")
                if not auto_fallback:
                    break

        # Todos falharam
        logger.error(f"All LLM providers failed. Last error: {last_error}")
        return LLMResponse(
            content=fallback_message,
            provider="fallback",
            model="none",
            success=False,
            error=last_error,
        )

    def list_providers(self) -> list[dict]:
        """Retorna lista de provedores ativos (para status/admin)."""
        self._ensure_initialized()
        return [
            {"name": name, "display_name": p.config.get("name", name), "enabled": True}
            for name, p in self._providers
        ]


# Singleton global
llm_manager = LLMManager()
