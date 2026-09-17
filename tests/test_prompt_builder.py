"""Testes do construtor de prompt (app/ai/llm/prompt_builder.py).

Testa a MONTAGEM do prompt (substituição de variáveis, ordem das
mensagens, presença das instruções) — não testa se a IA vai obedecer,
isso não dá pra garantir sem chamar o modelo de verdade (ver
scripts/tutor_eval.py pra isso). Aqui é só "o texto que a gente manda
pra IA está certo".
"""
from app.ai.llm.prompt_builder import build_tutor_messages


def test_nome_do_aluno_e_substituido_no_prompt():
    messages = build_tutor_messages(
        user_message="oi",
        scope="SOMENTE_QUESTAO_ATUAL",
        student_name="Zé",
    )
    system = messages[0].content
    assert "Zé" in system
    assert "{student_name}" not in system


def test_sem_nome_usa_fallback_generico():
    messages = build_tutor_messages(user_message="oi", scope="SOMENTE_QUESTAO_ATUAL", student_name="")
    system = messages[0].content
    assert "aluno(a)" in system


def test_historico_vem_entre_sistema_e_mensagem_nova():
    history = [
        {"role": "user", "content": "primeira pergunta"},
        {"role": "assistant", "content": "primeira resposta"},
    ]
    messages = build_tutor_messages(
        user_message="pergunta nova",
        scope="SOMENTE_QUESTAO_ATUAL",
        history=history,
    )
    assert messages[0].role == "system"
    assert messages[1].role == "user" and messages[1].content == "primeira pergunta"
    assert messages[2].role == "assistant" and messages[2].content == "primeira resposta"
    assert messages[-1].role == "user" and messages[-1].content == "pergunta nova"


def test_historico_ignora_entradas_sem_conteudo():
    history = [{"role": "user", "content": ""}, {"role": "assistant", "content": "  "}]
    messages = build_tutor_messages(user_message="oi", scope="SOMENTE_QUESTAO_ATUAL", history=history)
    # Só sistema + mensagem nova — as duas entradas vazias do histórico somem.
    assert len(messages) == 2


def test_system_hint_aparece_no_prompt_quando_definido():
    messages = build_tutor_messages(
        user_message="oi",
        scope="SOMENTE_QUESTAO_ATUAL",
        system_hint="Regra especial de teste XPTO123",
    )
    assert "XPTO123" in messages[0].content


def test_sem_system_hint_nao_aparece_secao_extra():
    messages = build_tutor_messages(user_message="oi", scope="SOMENTE_QUESTAO_ATUAL", system_hint=None)
    assert "Instrução adicional:" not in messages[0].content


def test_explicacao_so_aparece_quando_include_explanation_true():
    messages_sem = build_tutor_messages(
        user_message="oi", scope="SOMENTE_QUESTAO_ATUAL",
        explanation="EXPLICACAO_SECRETA_XYZ", include_explanation=False,
    )
    assert "EXPLICACAO_SECRETA_XYZ" not in messages_sem[0].content

    messages_com = build_tutor_messages(
        user_message="oi", scope="SOMENTE_QUESTAO_ATUAL",
        explanation="EXPLICACAO_SECRETA_XYZ", include_explanation=True,
    )
    assert "EXPLICACAO_SECRETA_XYZ" in messages_com[0].content


def test_ultima_mensagem_e_sempre_a_pergunta_do_usuario_atual():
    messages = build_tutor_messages(user_message="pergunta final do usuario", scope="SOMENTE_QUESTAO_ATUAL")
    assert messages[-1].role == "user"
    assert messages[-1].content == "pergunta final do usuario"


def test_scope_desconhecido_cai_no_padrao_sem_quebrar():
    # Não deve lançar exceção mesmo com escopo que não existe no YAML.
    messages = build_tutor_messages(user_message="oi", scope="ESCOPO_QUE_NAO_EXISTE")
    assert messages[0].role == "system"
