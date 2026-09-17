"""Testes do filtro anti-vazamento (app/tutor/leak_guard.py).

Cada caso aqui corresponde a um vazamento REAL visto em produção durante
testes ao vivo com o tutor, ou a um falso-positivo achado em revisão de
código antes de virar bug em produção. Rodar esta suíte antes de mexer
em leak_guard.py de novo evita reintroduzir qualquer um desses problemas
já resolvidos.
"""
import pytest

from app.tutor.leak_guard import (
    response_leaks_answer,
    response_looks_like_leaked_reasoning,
)


class TestResponseLeaksAnswer:
    def test_vazamento_parcial_dentro_de_alternativa_maior(self):
        # Caso real: IA disse "vetor de caminho" sem repetir o texto
        # INTEIRO da alternativa correta.
        resp = (
            "O BGP é o único protocolo da lista que: Opera entre Sistemas "
            "Autônomos, Usa TCP (porta 179), Carrega o caminho completo de "
            "AS (vetor de caminho). Qual alternativa combina vetor de "
            "caminho + TCP porta 179?"
        )
        correct = ["Vetor de Caminho (Path-Vector) usando TCP na porta 179"]
        assert response_leaks_answer(resp, correct) is True

    def test_texto_identico_a_alternativa(self):
        resp = "Pense bem: a resposta é Vetor de Caminho, tenho certeza disso."
        assert response_leaks_answer(resp, ["Vetor de Caminho"]) is True

    def test_nao_bloqueia_frase_generica_compartilhada(self):
        # Achado em revisão de código: "a camada de" é comum demais pra
        # indicar vazamento sozinho, mesmo tendo 3+ palavras.
        resp = "A camada de rede cuida do roteamento, bem diferente do que a outra camada faz."
        correct = ["A camada de transporte garante entrega confiável"]
        assert response_leaks_answer(resp, correct) is False

    def test_nao_bloqueia_resposta_sem_relacao(self):
        resp = "Pensa bem: qual dessas características te parece mais decisiva pra roteamento externo?"
        correct = ["Vetor de Caminho (Path-Vector) usando TCP na porta 179"]
        assert response_leaks_answer(resp, correct) is False

    def test_alternativa_curta_exige_match_completo(self):
        # Menos de 3 palavras: só compara o texto inteiro, não fatia.
        assert response_leaks_answer("A resposta certa é OSPF, tenho certeza.", ["OSPF"]) is True
        assert response_leaks_answer("Pense em protocolos de roteamento.", ["OSPF"]) is False

    def test_ignora_acentuacao_e_maiusculas(self):
        resp = "aquela opção usa VETOR DE CAMINHO como mecanismo principal"
        assert response_leaks_answer(resp, ["Vetor de caminho"]) is True

    def test_sem_alternativas_corretas_nunca_bloqueia(self):
        assert response_leaks_answer("qualquer coisa aqui", []) is False

    def test_resposta_vazia_nunca_bloqueia(self):
        assert response_leaks_answer("", ["Vetor de Caminho"]) is False


class TestResponseLooksLikeLeakedReasoning:
    def test_raciocinio_cru_variante_1(self):
        resp = (
            "Okay, let's see. The student is really struggling with this BGP "
            "question and keeps asking for hints. The alternatives are: "
            "1. Flooding in Layer 2 2. Pure Distance Vector based on hop count"
        )
        assert response_looks_like_leaked_reasoning(resp) is True

    def test_raciocinio_cru_variante_2(self):
        resp = (
            "Okay, the student is really stuck on this BGP question and keeps "
            "asking for hints. Let me recap where we are."
        )
        assert response_looks_like_leaked_reasoning(resp) is True

    def test_raciocinio_com_aspas_tipograficas(self):
        resp = "They’re struggling with this concept — let’s give a hint."
        assert response_looks_like_leaked_reasoning(resp) is True

    def test_nao_bloqueia_aula_legitima_sobre_ingles(self):
        # Achado em revisão de código: "the" sozinho é comum demais pra
        # indicar vazamento — apareceria em qualquer aula sobre inglês.
        resp = 'Repare que "the" é usado antes de substantivo definido: "the dog", "the book", "the car".'
        assert response_looks_like_leaked_reasoning(resp) is False

    def test_nao_bloqueia_resposta_normal_em_portugues(self):
        resp = "Pensa bem: qual dessas características te parece mais decisiva pra roteamento externo?"
        assert response_looks_like_leaked_reasoning(resp) is False

    def test_uma_unica_ocorrencia_nao_basta(self):
        # Uma palavra isolada em inglês não é sinal forte o bastante sozinha.
        resp = "Isso é um bom insight, vamos continuar pensando no assunto."
        assert response_looks_like_leaked_reasoning(resp) is False
