"""
Interface base para provedores de LLM.
Todo provedor deve herdar desta classe.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMMessage:
    role: str   # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    success: bool
    error: str | None = None


class BaseLLMProvider(ABC):
    """Interface base para todos os provedores de LLM."""

    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("name", "Unknown")

    @property
    def enabled(self) -> bool:
        return self.config.get("enabled", False)

    @abstractmethod
    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """Envia mensagens e retorna a resposta do LLM."""
        pass

    def _get_params(self, **overrides) -> dict:
        """Retorna parâmetros mesclados com overrides."""
        params = dict(self.config.get("parameters", {}))
        params.update(overrides)
        return params
