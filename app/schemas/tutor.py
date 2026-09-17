from pydantic import BaseModel, Field
from uuid import UUID

class TutorHistoryItem(BaseModel):
    role: str  # "user" | "assistant"
    content: str = Field(max_length=2000)

class TutorAskRequest(BaseModel):
    attempt_id: UUID
    question_id: UUID | None = None
    message: str = Field(min_length=1, max_length=4000)
    # Últimas trocas da conversa (mandadas pelo frontend, que já mantém o
    # histórico visual) — sem isso, cada mensagem era tratada como se fosse
    # a primeira, e a IA repetia a mesma pergunta várias vezes sem perceber.
    history: list[TutorHistoryItem] = Field(default_factory=list, max_length=12)

class TutorAskResponse(BaseModel):
    message: str
    out_of_scope: bool
