"""Interface comum dos motores."""

from __future__ import annotations

from abc import ABC, abstractmethod
from app.tutor.schemas import TutorContext, TutorEngineResult


class TutorEngine(ABC):
    @abstractmethod
    async def generate(self, *, context: TutorContext, user_message: str) -> TutorEngineResult:
        raise NotImplementedError
