"""Testes da árvore de decisão do tutor (app/ai/decision_tree/engine.py).

Testa CADA ramo de configs/decision_tree.yaml com um contexto mínimo —
puramente determinístico, sem IA nem banco de dados envolvidos. O tipo
de bug que isso pega é do tipo "AttemptStatus.STARTED não existe" ou
"contagem de dicas off-by-one": erros de lógica na hora de decidir QUAL
ação tomar, independente de qualquer resposta gerada por IA.
"""
from app.ai.decision_tree.engine import evaluate, build_tutor_context


def _ctx(**overrides) -> dict:
    base = build_tutor_context(
        tentativas_usadas=0,
        max_tentativas=3,
        dicas_usadas=0,
        max_dicas=3,
        acertou=None,
        modo_questionario="ESTUDO",
        escopo_tutor="SOMENTE_QUESTAO_ATUAL",
        fora_escopo=False,
        tem_explicacao=True,
    )
    base.update(overrides)
    return base


class TestArvorePrincipal:
    def test_fora_de_escopo_bloqueia_antes_de_tudo(self):
        # Mesmo com tudo mais "normal", fora_escopo=True tem prioridade.
        ctx = _ctx(fora_escopo=True, modo_questionario="AVALIACAO", acertou=True)
        result = evaluate(ctx)
        assert result.action == "BLOCK_OUT_OF_SCOPE"

    def test_modo_avaliacao_restringe_ajuda(self):
        ctx = _ctx(modo_questionario="AVALIACAO")
        result = evaluate(ctx)
        assert result.action == "SEND_RESTRICTED_HELP"

    def test_acertou_manda_reforco_positivo(self):
        ctx = _ctx(acertou=True)
        result = evaluate(ctx)
        assert result.action == "SEND_POSITIVE_REINFORCEMENT"

    def test_acertou_tem_prioridade_sobre_tentativas_esgotadas(self):
        # Se acertou=True, não importa que as tentativas também estejam
        # esgotadas — reforço positivo vem primeiro na árvore.
        ctx = _ctx(acertou=True, tentativas_usadas=3, max_tentativas=3)
        result = evaluate(ctx)
        assert result.action == "SEND_POSITIVE_REINFORCEMENT"

    def test_tentativas_esgotadas_libera_explicacao_completa(self):
        ctx = _ctx(acertou=False, tentativas_usadas=3, max_tentativas=3)
        result = evaluate(ctx)
        assert result.action == "SEND_FULL_EXPLANATION"

    def test_tentativas_esgotadas_operador_gte_pega_excesso_tambem(self):
        # gte: tentativas MAIORES que o máximo (não só iguais) também contam.
        ctx = _ctx(acertou=False, tentativas_usadas=5, max_tentativas=3)
        result = evaluate(ctx)
        assert result.action == "SEND_FULL_EXPLANATION"

    def test_dicas_disponiveis_oferece_dica(self):
        ctx = _ctx(acertou=False, tentativas_usadas=1, dicas_usadas=0, max_dicas=3)
        result = evaluate(ctx)
        assert result.action == "OFFER_HINT"
        assert result.hint_level_next is True

    def test_dicas_esgotadas_com_explicacao_vai_pro_llm_com_contexto(self):
        ctx = _ctx(acertou=False, tentativas_usadas=1, dicas_usadas=3, max_dicas=3, tem_explicacao=True)
        result = evaluate(ctx)
        assert result.action == "SEND_TO_LLM"
        assert result.include_explanation is True

    def test_dicas_esgotadas_sem_explicacao_vai_pro_llm_livre(self):
        ctx = _ctx(acertou=False, tentativas_usadas=1, dicas_usadas=3, max_dicas=3, tem_explicacao=False)
        result = evaluate(ctx)
        assert result.action == "SEND_TO_LLM"
        assert result.include_explanation is False

    def test_arvore_sempre_retorna_algo_mesmo_com_contexto_incompleto(self):
        # evaluate() nunca deve retornar None, mesmo faltando chave no ctx.
        result = evaluate({})
        assert result is not None
        assert result.action  # sempre tem alguma ação, nem que seja SEND_TO_LLM


class TestArvoreFeedback:
    def _feedback_ctx(self, **overrides):
        base = {
            "modo_questionario": "ESTUDO",
            "acertou": False,
            "tentativas_usadas": 0,
            "max_tentativas": 3,
        }
        base.update(overrides)
        return base

    def test_acertou_da_feedback_correto(self):
        ctx = self._feedback_ctx(acertou=True)
        result = evaluate(ctx, tree_name="feedback_decision_tree")
        assert result.action == "FEEDBACK_CORRECT"
        assert result.show_explanation is True

    def test_errou_com_tentativas_restantes_pede_tentar_de_novo(self):
        ctx = self._feedback_ctx(acertou=False, tentativas_usadas=1, max_tentativas=3)
        result = evaluate(ctx, tree_name="feedback_decision_tree")
        assert result.action == "FEEDBACK_WRONG_RETRY"
        assert result.show_correct_answer is False

    def test_errou_na_ultima_tentativa_mostra_resposta_certa(self):
        ctx = self._feedback_ctx(acertou=False, tentativas_usadas=3, max_tentativas=3)
        result = evaluate(ctx, tree_name="feedback_decision_tree")
        assert result.action == "FEEDBACK_WRONG_FINAL"
        assert result.show_correct_answer is True

    def test_modo_avaliacao_nunca_mostra_explicacao_nem_resposta(self):
        ctx = self._feedback_ctx(modo_questionario="AVALIACAO", acertou=True)
        result = evaluate(ctx, tree_name="feedback_decision_tree")
        assert result.action == "FEEDBACK_EVALUATION_MODE"
        assert result.show_explanation is False
        assert result.show_correct_answer is False

    def test_modo_diagnostico_trata_igual_estudo(self):
        ctx = self._feedback_ctx(modo_questionario="DIAGNOSTICO", acertou=True)
        result = evaluate(ctx, tree_name="feedback_decision_tree")
        assert result.action == "FEEDBACK_CORRECT"
