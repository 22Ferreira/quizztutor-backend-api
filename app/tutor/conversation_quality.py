"""Detecção de padrões de conversa ruim, ao longo de VÁRIAS respostas.

leak_guard.py julga uma resposta isolada (vaza ou não vaza a resposta
certa). Este módulo julga o padrão ao longo do tempo — os problemas mais
reclamados nesta sessão não estavam numa resposta só, estavam na
SEQUÊNCIA: a mesma pergunta reaparecendo reformulada, o mesmo abridor de
frase repetido, ou pergunta emendada em toda resposta mesmo quando o
aluno já errou e só queria entender o que aconteceu.

Puramente determinístico (comparação de texto), sem chamada de IA —
serve tanto pra testar com transcrições reais já vistas (tests/) quanto
pra julgar automaticamente uma conversa gerada de verdade (scripts/).
"""
from __future__ import annotations

import re
import unicodedata

_QUESTION_RE = re.compile(r"[^.!?]*\?", re.MULTILINE)
_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def count_questions(text: str) -> int:
    """Quantas frases terminadas em '?' existem na resposta."""
    return text.count("?")


def extract_questions(text: str) -> list[str]:
    """Extrai cada trecho que termina em '?' (a "pergunta" da resposta)."""
    return [q.strip() for q in _QUESTION_RE.findall(text) if q.strip()]


def _word_set(text: str) -> set[str]:
    return set(_WORD_RE.findall(_normalize(text)))


def _similarity(a: str, b: str) -> float:
    """Similaridade simples por sobreposição de palavras (Jaccard)."""
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


# Duas perguntas de fechamento contam como "a mesma reformulada" quando
# compartilham 45%+ das palavras. Medido em cima de casos reais: a
# reformulação óbvia ("qual atributo ajuda mais" / "qual atributo
# influencia mais", vista em produção) dá 0.50 de similaridade; perguntas
# genuinamente diferentes ficam abaixo de 0.05 — a margem é folgada.
_SIMILARITY_THRESHOLD = 0.45


def find_repeated_questions(tutor_responses: list[str]) -> list[tuple[int, int, str, str]]:
    """Acha pares de respostas cuja pergunta de fechamento é essencialmente
    a mesma. Retorna (índice_a, índice_b, pergunta_a, pergunta_b)."""
    last_questions: list[tuple[int, str]] = []
    for i, resp in enumerate(tutor_responses):
        questions = extract_questions(resp)
        if not questions:
            continue
        last_questions.append((i, questions[-1]))

    repeats = []
    for idx in range(1, len(last_questions)):
        i, qi = last_questions[idx]
        j, qj = last_questions[idx - 1]
        if _similarity(qi, qj) >= _SIMILARITY_THRESHOLD:
            repeats.append((j, i, qj, qi))
    return repeats


# 2 palavras, não 3: o padrão real visto em produção era "Entendo que..."
# seguido de conteúdo DIFERENTE ("Entendo que você...", "Entendo que
# essa..." — só as 2 primeiras palavras repetem, a 3ª já varia).
_OPENER_WORDS = 2


def _opener(text: str) -> str:
    words = _normalize(text).split()[:_OPENER_WORDS]
    return " ".join(words)


def find_repeated_openers(tutor_responses: list[str]) -> list[tuple[int, int, str]]:
    """Acha respostas CONSECUTIVAS que começam com as mesmas palavras
    (ex: "Entendo que..." toda hora)."""
    repeats = []
    for i in range(1, len(tutor_responses)):
        a, b = _opener(tutor_responses[i - 1]), _opener(tutor_responses[i])
        if a and a == b:
            repeats.append((i - 1, i, a))
    return repeats


def fraction_ending_in_question(tutor_responses: list[str]) -> float:
    """Proporção das respostas que terminam (ignorando espaço) com '?'."""
    if not tutor_responses:
        return 0.0
    ending = sum(1 for r in tutor_responses if r.strip().endswith("?"))
    return ending / len(tutor_responses)


# Palavras que indicam a IA está encorajando o aluno a ir responder —
# usado pra checar se, depois de insistência, ELA de fato afrouxa em vez
# de só continuar perguntando.
_RELEASE_MARKERS = (
    "marcar", "marque", "responda", "pode ir em frente", "vai em frente",
    "confia", "confiante", "arrisca", "arriscar",
)


def looks_like_release(text: str) -> bool:
    normalized = _normalize(text)
    return any(marker in normalized for marker in _RELEASE_MARKERS)
