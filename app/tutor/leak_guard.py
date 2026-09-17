"""Rede de segurança determinística contra vazamento de resposta.

O prompt (tutor_prompts.yaml) instrui a IA a nunca revelar a alternativa
correta, mas isso é só instrução — a IA segue por tendência, não por
lógica rígida, e testes ao vivo já mostraram ela cruzando essa linha
mais de uma vez (inclusive escalando demais em pedidos repetidos de
dica). Esta checagem roda DEPOIS da IA responder, comparando o texto
gerado com o texto literal da alternativa correta — sem nunca ter
mandado esse texto pra IA, então não depende dela "lembrar" de regra
nenhuma.

Pega vazamento LITERAL (a IA escreve o texto da alternativa certa).
Não pega vazamento por dedução indireta (explicar tão bem o critério
que só sobra uma opção possível, sem nunca citar o nome dela) — isso
continua dependendo só do prompt.
"""
import re
import unicodedata


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Texto curto demais (ex: "A", "Sim") geraria falso positivo praticamente
# certo — comparação só é confiável a partir de um tamanho mínimo.
_MIN_LEN_FOR_MATCH = 6


def response_leaks_answer(response_text: str, correct_option_texts: list[str]) -> bool:
    """True se o texto da resposta contém, literalmente, o texto de
    alguma alternativa marcada como correta."""
    normalized_response = _normalize(response_text)
    for opt_text in correct_option_texts:
        normalized_opt = _normalize(opt_text)
        if len(normalized_opt) < _MIN_LEN_FOR_MATCH:
            continue
        if normalized_opt in normalized_response:
            return True
    return False


SAFE_REDIRECT_MESSAGE = (
    "Opa, percebi que ia acabar te entregando a resposta pronta demais — "
    "vamos por outro caminho. Pensa nas características que já comparamos: "
    "qual delas combina com o que você já sabe sobre o assunto? Você está "
    "mais perto do que imagina."
)
