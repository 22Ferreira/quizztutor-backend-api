"""
Construtor de prompts para o tutor.
Usa o tutor_prompts.yaml para montar os prompts de sistema e usuário.
"""
import logging
import random
from typing import Any

from app.ai.configs.loader import get_tutor_prompts
from app.ai.providers.base import LLMMessage

logger = logging.getLogger(__name__)


def build_tutor_messages(
    *,
    user_message: str,
    scope: str,
    quiz_title: str = "",
    question_statement: str = "",
    options_text: str = "",
    topic: str = "",
    objective: str = "",
    explanation: str = "",
    custom_system_prompt: str | None = None,
    include_explanation: bool = False,
    system_hint: str | None = None,
    student_name: str = "",
    history: list[dict] | None = None,
) -> list[LLMMessage]:
    """
    Monta a lista de mensagens para enviar ao LLM.
    Usa os templates do tutor_prompts.yaml.
    """
    prompts_cfg = get_tutor_prompts()

    base_prompt = prompts_cfg.get("base_system_prompt", "Você é um tutor educacional. Responda em português.")
    scope_prompts = prompts_cfg.get("scope_prompts", {})
    response_style = prompts_cfg.get("response_style", {})

    # .replace em vez de .format: base_prompt não tem outros placeholders
    # definidos, então .format() quebraria se alguém digitasse uma chave
    # {algo} sem querer ao editar o YAML.
    base_prompt = base_prompt.replace("{student_name}", student_name or "aluno(a)")

    # Montar scope prompt
    scope_template = scope_prompts.get(scope, scope_prompts.get("SOMENTE_QUESTAO_ATUAL", ""))
    scope_content = scope_template.format(
        quiz_title=quiz_title,
        question=question_statement,
        options=options_text,
        topic=topic or "não especificado",
        objective=objective or "não especificado",
    )

    # Montar system completo
    system_parts = [base_prompt.strip()]
    if custom_system_prompt:
        system_parts.append(f"\n\nInstruções específicas:\n{custom_system_prompt.strip()}")
    system_parts.append(f"\n\nContexto:\n{scope_content.strip()}")

    if include_explanation and explanation:
        system_parts.append(f"\n\nExplicação da questão (use como base, não copie literalmente):\n{explanation}")

    if system_hint:
        system_parts.append(f"\n\nInstrução adicional: {system_hint}")

    if response_style.get("socratic_questions", True):
        socratic_hint = response_style.get("socratic_question_prompt", "")
        if socratic_hint:
            system_parts.append(f"\n\n{socratic_hint.strip()}")

    max_length = response_style.get("max_length_chars", 800)
    system_parts.append(f"\n\nSeja conciso. Limite sua resposta a {max_length} caracteres.")

    system_content = "\n".join(system_parts)

    # Histórico recente entra ANTES da mensagem nova — é o que permite a IA
    # perceber que já respondeu isso antes em vez de repetir a mesma
    # pergunta socrática em loop, e escalar o nível de ajuda se o aluno
    # já insistiu várias vezes sem conseguir.
    history_messages = [
        LLMMessage(role="assistant" if h.get("role") == "assistant" else "user", content=h.get("content", "").strip())
        for h in (history or [])
        if h.get("content", "").strip()  # "  " é truthy em Python — sem .strip() aqui, passava direto
    ]

    return [
        LLMMessage(role="system", content=system_content),
        *history_messages,
        LLMMessage(role="user", content=user_message),
    ]


def get_positive_reinforcement() -> str:
    """Retorna uma mensagem aleatória de reforço positivo."""
    prompts_cfg = get_tutor_prompts()
    messages = prompts_cfg.get("messages", {}).get("positive_reinforcement", [])
    if messages:
        return random.choice(messages)
    return "Correto! ✅"


def get_encouragement(topic: str = "") -> str:
    """Retorna mensagem de encorajamento para resposta errada."""
    prompts_cfg = get_tutor_prompts()
    messages = prompts_cfg.get("messages", {}).get("encouragement_wrong", [])
    if messages:
        template = random.choice(messages)
        return template.format(topic=topic or "o assunto")
    return "Tente novamente!"


def get_message(key: str, **kwargs) -> str:
    """Busca uma mensagem template do YAML e aplica formatação."""
    prompts_cfg = get_tutor_prompts()
    msg = prompts_cfg.get("messages", {}).get(key, "")
    if isinstance(msg, str) and msg:
        try:
            return msg.format(**kwargs)
        except KeyError:
            return msg
    return ""
