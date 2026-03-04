"""
Motor de árvore de decisão.
Lê a config YAML e executa os nós de decisão com base no contexto do tutor.

Contexto esperado (dict):
  tentativas_usadas, max_tentativas, dicas_usadas, max_dicas,
  acertou, modo_questionario, escopo_tutor, fora_escopo,
  tem_explicacao, nivel_dificuldade, interacoes_tutor_total
"""
import logging
from dataclasses import dataclass, field
from typing import Any

from app.ai.configs.loader import get_decision_tree

logger = logging.getLogger(__name__)


@dataclass
class DecisionResult:
    """Resultado da execução da árvore de decisão."""
    action: str                          # Ação a executar (ex: SEND_TO_LLM, OFFER_HINT)
    message_template: str | None = None  # Template de mensagem pronta (ou None para chamar LLM)
    log_interaction: bool = True
    log_kind: str = "RESPOSTA_TUTOR"
    hint_level_next: bool = False        # Usar próximo nível de dica
    include_explanation: bool = False    # Incluir explicação da questão no contexto LLM
    system_hint: str | None = None       # Instrução adicional para o LLM
    show_explanation: bool = False
    show_correct_answer: bool = False
    extra: dict = field(default_factory=dict)


def _evaluate_condition(condition: dict, ctx: dict) -> bool:
    """Avalia uma condição simples contra o contexto."""
    field_name = condition.get("field")
    operator = condition.get("operator", "eq")
    value = condition.get("value")
    value_from_field = condition.get("value_from_field")

    ctx_value = ctx.get(field_name)

    # Resolve valor comparado
    if value_from_field:
        compare_to = ctx.get(value_from_field)
    else:
        compare_to = value

    try:
        if operator == "eq":
            return ctx_value == compare_to
        elif operator == "neq":
            return ctx_value != compare_to
        elif operator == "gt":
            return float(ctx_value or 0) > float(compare_to or 0)
        elif operator == "gte":
            return float(ctx_value or 0) >= float(compare_to or 0)
        elif operator == "lt":
            return float(ctx_value or 0) < float(compare_to or 0)
        elif operator == "lte":
            return float(ctx_value or 0) <= float(compare_to or 0)
        elif operator == "in":
            return ctx_value in (compare_to or [])
        elif operator == "not_in":
            return ctx_value not in (compare_to or [])
        elif operator == "is_null":
            return ctx_value is None
        elif operator == "not_null":
            return ctx_value is not None
        else:
            logger.warning(f"Unknown operator: {operator}")
            return False
    except Exception as e:
        logger.error(f"Condition eval error: {e} | field={field_name} op={operator} val={compare_to} ctx={ctx_value}")
        return False


def _node_to_result(node: dict) -> DecisionResult:
    """Converte um nó de ação em DecisionResult."""
    return DecisionResult(
        action=node.get("action", "SEND_TO_LLM"),
        message_template=node.get("message_template"),
        log_interaction=node.get("log_interaction", True),
        log_kind=node.get("log_kind", "RESPOSTA_TUTOR"),
        hint_level_next=node.get("hint_level_next", False),
        include_explanation=node.get("include_explanation", False),
        system_hint=node.get("system_hint"),
        show_explanation=node.get("show_explanation", False),
        show_correct_answer=node.get("show_correct_answer", False),
        extra=node.get("extra", {}),
    )


def _walk_nodes(nodes: list, ctx: dict) -> DecisionResult | None:
    """Percorre recursivamente os nós da árvore."""
    for node in nodes:
        node_type = node.get("type")

        if node_type == "action":
            return _node_to_result(node)

        elif node_type == "condition":
            condition = node.get("condition", {})
            passed = _evaluate_condition(condition, ctx)
            branch = node.get("then" if passed else "else", [])
            result = _walk_nodes(branch, ctx)
            if result:
                return result

    return None


def evaluate(ctx: dict, tree_name: str = "tutor_decision_tree") -> DecisionResult:
    """
    Avalia o contexto na árvore de decisão configurada.
    Retorna sempre um DecisionResult (nunca None).
    """
    config = get_decision_tree()
    nodes = config.get(tree_name, [])

    if not nodes:
        logger.warning(f"Decision tree '{tree_name}' not found or empty. Falling back to LLM.")
        return DecisionResult(action="SEND_TO_LLM")

    result = _walk_nodes(nodes, ctx)

    if result is None:
        logger.warning(f"No decision reached in tree '{tree_name}'. Falling back to LLM.")
        return DecisionResult(action="SEND_TO_LLM")

    logger.debug(f"Decision tree result: action={result.action} tree={tree_name}")
    return result


def build_tutor_context(
    *,
    tentativas_usadas: int,
    max_tentativas: int,
    dicas_usadas: int,
    max_dicas: int,
    acertou: bool | None,
    modo_questionario: str,
    escopo_tutor: str,
    fora_escopo: bool,
    tem_explicacao: bool,
    nivel_dificuldade: str | None = None,
    interacoes_tutor_total: int = 0,
) -> dict:
    """Helper para montar o contexto da árvore de decisão."""
    return {
        "tentativas_usadas": tentativas_usadas,
        "max_tentativas": max_tentativas,
        "dicas_usadas": dicas_usadas,
        "max_dicas": max_dicas,
        "acertou": acertou,
        "modo_questionario": modo_questionario,
        "escopo_tutor": escopo_tutor,
        "fora_escopo": fora_escopo,
        "tem_explicacao": tem_explicacao,
        "nivel_dificuldade": nivel_dificuldade,
        "interacoes_tutor_total": interacoes_tutor_total,
    }
