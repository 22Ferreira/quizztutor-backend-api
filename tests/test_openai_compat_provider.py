"""Testes das checagens de conteúdo do provedor OpenAI-compatible
(app/ai/providers/openai_compat.py) — Groq, OpenRouter, Ollama.

Não testa a chamada HTTP em si (precisaria de rede/mocks pesados), só
as funções puras que decidem se um conteúdo retornado é uma resposta
válida ou precisa ser tratado como falha do provedor.
"""
from app.ai.providers.openai_compat import (
    _looks_like_safety_classifier_output,
    _strip_reasoning,
)


class TestSafetyClassifierDetection:
    def test_detecta_saida_real_de_classificador(self):
        # Caso real: o roteador automático da OpenRouter escolheu um
        # modelo de moderação (tipo Llama Guard) em vez de conversa.
        content = "User Safety: safe\nResponse Safety: safe"
        assert _looks_like_safety_classifier_output(content) is True

    def test_detecta_variante_unsafe(self):
        assert _looks_like_safety_classifier_output("Response Safety: unsafe") is True

    def test_nao_bloqueia_resposta_normal(self):
        resp = "Pensa bem: qual dessas alternativas parece mais correta?"
        assert _looks_like_safety_classifier_output(resp) is False

    def test_nao_bloqueia_resposta_que_menciona_seguranca(self):
        # "segurança" aparecendo no meio do texto não pode disparar —
        # só o formato específico de classificador no INÍCIO da resposta.
        resp = "A questão fala sobre segurança de rede e criptografia de dados."
        assert _looks_like_safety_classifier_output(resp) is False

    def test_resposta_vazia_nao_dispara(self):
        assert _looks_like_safety_classifier_output("") is False


class TestStripReasoning:
    def test_remove_tag_think_fechada(self):
        content = "<think>raciocínio interno aqui</think>Resposta de verdade pro aluno."
        assert _strip_reasoning(content) == "Resposta de verdade pro aluno."

    def test_remove_tag_think_sem_fechar(self):
        content = "Início normal <think>raciocínio cortado no meio"
        assert _strip_reasoning(content) == "Início normal"

    def test_sem_tag_nao_muda_nada(self):
        content = "Resposta normal sem raciocínio vazando."
        assert _strip_reasoning(content) == content
