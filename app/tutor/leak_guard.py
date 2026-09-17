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
   por trecho (n-grama) que exige palavras de CONTEÚDO, não só qualquer
   trecho de 3 palavras — "a camada de" apareceria em qualquer resposta
   sobre camadas de rede e não indicaria vazamento nenhum por si só.
2. response_looks_like_leaked_reasoning(): detecta raciocínio interno
   vazando em inglês (o tutor só deveria responder em português) — nem
   sempre vem marcado com <think>, às vezes é só prosa solta tipo
   "Okay, let's see, the student is...". Usa só marcadores bem
   distintos de monólogo interno (não palavras comuns tipo "the", que
   apareceriam normalmente numa aula de inglês, por exemplo).
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

# Palavras de função em português — um trecho composto majoritariamente
# por elas (ex: "a camada de") é genérico demais pra indicar vazamento,
# mesmo tendo 3+ palavras. Só conta como vazamento real se o trecho tiver
# mais palavras de CONTEÚDO do que de função.
_PT_STOPWORDS = {
    "a", "o", "as", "os", "de", "do", "da", "dos", "das", "em", "no", "na",
    "nos", "nas", "um", "uma", "uns", "umas", "e", "ou", "que", "com",
    "para", "por", "se", "e", "ao", "aos", "a", "as", "mais", "muito",
    "como", "mas", "tambem", "ja", "seu", "sua", "seus", "suas", "este",
    "esta", "isso", "isto", "ele", "ela", "eles", "elas", "entre", "sobre",
    "sem", "sao", "ser", "esta", "estao", "foi", "eh", "nao", "sim",
}


def _is_meaningful_ngram(words: list[str]) -> bool:
    content_words = [w for w in words if w not in _PT_STOPWORDS and len(w) > 2]
    return len(content_words) >= max(2, (len(words) // 2) + 1)


def _contains_ngram_leak(response_norm: str, option_norm: str) -> bool:
    words = option_norm.split()
    if len(words) < _MIN_NGRAM_WORDS:
        # Alternativa já é curta (poucas palavras) — só vale comparar o
        # texto inteiro dela, não dá pra fatiar mais que isso.
        return len(option_norm) >= _MIN_LEN_FOR_MATCH and option_norm in response_norm
    for n in range(len(words), _MIN_NGRAM_WORDS - 1, -1):
        for i in range(len(words) - n + 1):
            phrase_words = words[i:i + n]
            if not _is_meaningful_ngram(phrase_words):
                continue
            phrase = " ".join(phrase_words)
            if len(phrase) >= _MIN_LEN_FOR_MATCH and phrase in response_norm:
                return True
    return False


def response_leaks_answer(response_text: str, correct_option_texts: list[str]) -> bool:
    """True se o texto da resposta contém um trecho reconhecível (3+
    palavras seguidas, com conteúdo real) de alguma alternativa correta."""
    normalized_response = _normalize(response_text)
    for opt_text in correct_option_texts:
        normalized_opt = _normalize(opt_text)
        if not normalized_opt:
            continue
        if _contains_ngram_leak(normalized_response, normalized_opt):
            return True
    return False


# Marcadores de MONÓLOGO INTERNO em inglês — não palavras comuns isoladas
# (tipo "the" ou "alternative", que podem aparecer legitimamente numa
# resposta sobre um assunto de língua inglesa), só frases/termos que só
# fazem sentido como o modelo "pensando em voz alta" sobre o aluno.
# Tolera aspas retas e curvas (') e (').
_ENGLISH_TELLS_RE = re.compile(
    r"(okay|let'?s|let me|i think|i'll|they'?ve|they'?re|"
    r"the student is|struggling|here'?s where we are|recap|"
    r"the alternatives are)",
    re.IGNORECASE,
)
_ENGLISH_TELLS_MIN_HITS = 2


def response_looks_like_leaked_reasoning(response_text: str) -> bool:
    """True se o texto tem marcadores fortes de monólogo interno em
    inglês em quantidade — sinal de raciocínio do modelo vazando em vez
    da resposta final em português."""
    normalized = response_text.replace("’", "'").replace("‘", "'").replace("`", "'")
    hits = _ENGLISH_TELLS_RE.findall(normalized)
    return len(hits) >= _ENGLISH_TELLS_MIN_HITS


SAFE_REDIRECT_MESSAGE = (
    "Opa, percebi que ia acabar te entregando a resposta pronta demais — "
    "vamos por outro caminho. Pensa nas características que já comparamos: "
    "qual delas combina com o que você já sabe sobre o assunto? Você está "
    "mais perto do que imagina."
)
