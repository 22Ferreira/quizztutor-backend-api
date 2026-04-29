"""app.tutor.rules.guardrails

REGRAS que valem para qualquer motor.
O motor só gera texto; o TutorService decide se pode gerar.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuardrailDecision:
    allowed: bool
    reason: str = ""
    user_message: str = ""


def evaluate_guardrails(*, is_attempt_active: bool, is_quiz_open: bool, out_of_scope: bool, evaluation_mode: bool) -> GuardrailDecision:
    if not is_attempt_active:
        return GuardrailDecision(False, "ATTEMPT_INACTIVE", "Sua tentativa está encerrada/expirada. Não consigo ajudar por aqui.")
    if not is_quiz_open:
        return GuardrailDecision(False, "QUIZ_CLOSED", "Este questionário está fechado. Não consigo iniciar novas ajudas.")
    if out_of_scope:
        return GuardrailDecision(False, "OUT_OF_SCOPE", "Isso foge do escopo do tutor para este questionário. Vamos focar na questão atual?")
    # Em avaliação você pode bloquear completamente se quiser:
    # if evaluation_mode: return GuardrailDecision(False, "EVALUATION", "Durante avaliação não posso ajudar.")
    return GuardrailDecision(True, "OK", "")
