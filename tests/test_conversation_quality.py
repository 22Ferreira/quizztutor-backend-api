"""Testes de detecção de ciclo/repetição — usam as transcrições REAIS
que motivaram cada correção nesta sessão como fixture, pra nunca perder
a capacidade de detectar esses padrões específicos de novo."""
from app.tutor.conversation_quality import (
    count_questions,
    find_repeated_openers,
    find_repeated_questions,
    fraction_ending_in_question,
    looks_like_release,
)


class TestPerguntaRepetida:
    def test_pega_pergunta_reformulada_caso_real_bgp(self):
        # Transcrição real: "explique" -> "quero mais detalhes" -> "melhores
        # mais", cada resposta terminando numa pergunta essencialmente igual.
        respostas = [
            "BGP funciona como vetor de caminho, cada AS troca rotas. "
            "Qual característica desse mecanismo faz ele diferir de um protocolo de estado de enlace?",
            "BGP mantém uma tabela de rotas por sessão TCP. "
            "Qual atributo do BGP você acha que ajuda mais na escolha do caminho mais favorável?",
            "BGP compara vetores de atributos pra decidir o caminho preferido. "
            "Qual atributo do BGP você acha que influencia mais a decisão de qual caminho usar?",
        ]
        repeats = find_repeated_questions(respostas)
        assert len(repeats) >= 1  # ao menos a 2ª e 3ª batem entre si

    def test_nao_acusa_perguntas_genuinamente_diferentes(self):
        respostas = [
            "Vamos começar pelo básico: qual protocolo você já estudou antes, OSPF ou RIP?",
            "Legal! E o que você lembra sobre como o OSPF descobre a topologia da rede?",
            "Boa observação. Agora pensa: isso funcionaria do mesmo jeito entre empresas diferentes?",
        ]
        assert find_repeated_questions(respostas) == []

    def test_uma_unica_resposta_nunca_acusa_repeticao(self):
        assert find_repeated_questions(["Só uma pergunta aqui, tudo bem?"]) == []


class TestAbridorRepetido:
    def test_pega_entendo_que_repetido(self):
        # Bug real corrigido nesta sessão: a IA sempre abrindo com a mesma
        # expressão ("Entendo que...") em respostas seguidas.
        respostas = [
            "Entendo que você está em dúvida sobre isso, vamos com calma.",
            "Entendo que essa parte confunde bastante gente, sem problemas.",
        ]
        repeats = find_repeated_openers(respostas)
        assert len(repeats) == 1

    def test_nao_acusa_abridores_diferentes(self):
        respostas = ["Boa pergunta! Vamos pensar juntos.", "Repara numa coisa: o BGP usa TCP."]
        assert find_repeated_openers(respostas) == []


class TestSempreTerminaEmPergunta:
    def test_deteta_todas_as_respostas_perguntando(self):
        # Caso do usuário: aluno só pede ajuda genérica repetidamente, IA
        # sempre fecha com pergunta mesmo sem nunca ter havido tentativa
        # de resposta — 100% das respostas terminando em "?" é o sintoma.
        respostas = [
            "Vamos pensar juntos, o que você já sabe sobre o assunto?",
            "Sem problemas! Qual parte específica ficou confusa?",
            "Entendido. Já ouviu falar em vetor de caminho antes?",
        ]
        assert fraction_ending_in_question(respostas) == 1.0

    def test_resposta_pos_erro_nao_devia_ser_so_pergunta(self):
        # Depois de "eu errei", uma resposta que É só pergunta (sem
        # explicação nenhuma antes) é exatamente o padrão que o usuário
        # reclamou — o teste documenta como isso seria identificado.
        resposta_ruim = "O que você acha que a assinatura digital realmente faz?"
        resposta_boa = (
            "Você marcou a chave privada, mas quem verifica a assinatura usa "
            "a chave PÚBLICA do remetente — é isso que garante que só ele "
            "poderia ter assinado. Faz sentido a diferença?"
        )
        # resposta ruim: pergunta praticamente ocupa a resposta inteira
        assert len(resposta_ruim) - len(resposta_ruim.rstrip("?").rstrip()) <= 1
        assert count_questions(resposta_ruim) == 1
        # resposta boa: tem bastante conteúdo ANTES da pergunta final
        primeira_pergunta_pos = resposta_boa.index("?")
        assert primeira_pergunta_pos > 80  # substância real antes de perguntar


class TestLiberacaoAposInsistencia:
    def test_reconhece_linguagem_de_liberacao(self):
        texto = "Você já disse algumas vezes que acha que é essa — se está confiante, pode ir em frente e marcar."
        assert looks_like_release(texto) is True

    def test_pura_pergunta_socratica_nao_e_liberacao(self):
        texto = "Qual característica você acha que diferencia essa alternativa das outras?"
        assert looks_like_release(texto) is False
