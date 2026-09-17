"""Rede de segurança determinística contra vazamento de resposta.

O prompt (tutor_prompts.yaml) instrui a IA a nunca revelar a alternativa
correta, mas isso é só instrução — a IA segue por tendência, não por
lógica rígida, e testes ao vivo já mostraram ela cruzando essa linha
mais de uma vez (inclusive escalando demais em pedidos repetidos de
dica, e vazando o próprio raciocínio interno em inglês). Esta checagem
roda DEPOIS da IA responder, sem depender dela seguir regra nenhuma.

Duas checagens independentes:
1. response_leaks_answer(): compara o texto gerado com o texto literal
   da alternativa correta (nunca enviado pra IA). Usa correspondência
   por trecho (n-grama), não só o texto inteiro da alternativa — a IA
   raramente repete uma alternativa inteira palavra por palavra, mas já
   vazou um TRECHO dela (ex: "vetor de caminho" dentro de uma alternativa
   maior) várias vezes em teste real.
2. response_looks_like_leaked_reasoning(): detecta raciocínio interno
   vazando em inglês (o tutor só deveria responder em português) — nem
   sempre vem marcado com <think>, às vezes é só prosa solta tipo
   "Okay, let's see, the student is...".
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
# Trecho contíguo mínimo de palavras da alternativa pra considerar vazamento
# real (1-2 palavras soltas geram falso positivo fácil demais).
_MIN_NGRAM_WORDS = 3


def _contains_ngram_leak(response_norm: str, option_norm: str) -> bool:
    words = option_norm.split()
    if len(words) < _MIN_NGRAM_WORDS:
        # Alternativa já é curta (poucas palavras) — só vale comparar o
        # texto inteiro dela, não dá pra fatiar mais que isso.
        return len(option_norm) >= _MIN_LEN_FOR_MATCH and option_norm in response_norm
    for n in range(len(words), _MIN_NGRAM_WORDS - 1, -1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i:i + n])
            if len(phrase) >= _MIN_LEN_FOR_MATCH and phrase in response_norm:
                return True
    return False


def response_leaks_answer(response_text: str, correct_option_texts: list[str]) -> bool:
    """True se o texto da resposta contém um trecho reconhecível (3+
    palavras seguidas) de alguma alternativa marcada como correta."""
    normalized_response = _normalize(response_text)
    for opt_text in correct_option_texts:
        normalized_opt = _normalize(opt_text)
        if not normalized_opt:
            continue
        if _contains_ngram_leak(normalized_response, normalized_opt):
            return True
    return False


# Palavras que praticamente só aparecem em inglês — se aparecerem várias
# vezes na mesma resposta, é sinal forte de raciocínio interno vazando
# (o tutor só deveria responder em português brasileiro).
_ENGLISH_TELLS_RE = re.compile(
    r"\b(the|okay|let'?s|i think|i'll|they've|they're|student is|"
    r"alternative[s]?|struggling|let me|here'?s|wait|hint[s]?)\b",
    re.IGNORECASE,
)
_ENGLISH_TELLS_MIN_HITS = 3


def response_looks_like_leaked_reasoning(response_text: str) -> bool:
    """True se o texto tem marcadores fortes de inglês em quantidade —
    sinal de raciocínio interno do modelo vazando em vez da resposta
    final em português."""
    hits = _ENGLISH_TELLS_RE.findall(response_text)
    return len(hits) >= _ENGLISH_TELLS_MIN_HITS


SAFE_REDIRECT_MESSAGE = (
    "Opa, percebi que ia acabar te entregando a resposta pronta demais — "
    "vamos por outro caminho. Pensa nas características que já comparamos: "
    "qual delas combina com o que você já sabe sobre o assunto? Você está "
    "mais perto do que imagina."
)
