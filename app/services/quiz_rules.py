from fastapi import HTTPException
from app.models.quiz import Quiz, QuizQuestion, QuizMode


def validate_publish(quiz: Quiz):
    """Validate all rules before publishing — per official lifecycle."""
    if not quiz.questions or len(quiz.questions) < 1:
        raise HTTPException(status_code=400, detail="Quiz precisa ter pelo menos 1 questão")

    if not quiz.title or len(quiz.title.strip()) < 3:
        raise HTTPException(status_code=400, detail="Título precisa ter pelo menos 3 caracteres")

    if quiz.availability_start and quiz.availability_end:
        if quiz.availability_start >= quiz.availability_end:
            raise HTTPException(status_code=400, detail="Janela de disponibilidade inválida")

    mode = quiz.tempo_mode if isinstance(quiz.tempo_mode, str) else quiz.tempo_mode.value

    if mode == "TOTAL":
        if not quiz.time_total_seconds or quiz.time_total_seconds <= 0:
            raise HTTPException(status_code=400, detail="Modo TOTAL exige tempo total > 0")

    elif mode == "PER_QUESTION":
        if not quiz.time_default_question_seconds or quiz.time_default_question_seconds <= 0:
            raise HTTPException(status_code=400, detail="Modo PER_QUESTION exige tempo padrão > 0")

    elif mode == "MIXED":
        tbd = quiz.time_by_difficulty or {}
        for diff in ("FACIL", "MEDIA", "DIFICIL"):
            val = tbd.get(diff)
            if not val or int(val) <= 0:
                raise HTTPException(status_code=400, detail=f"Modo MIXED exige tempo para '{diff}' > 0")
        for q in quiz.questions:
            if q.difficulty not in ("FACIL", "MEDIA", "DIFICIL"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Questão {q.order+1}: modo MIXED exige dificuldade definida"
                )
    # mode == "NONE": sem validação de tempo

    for q in quiz.questions:
        n = q.order + 1
        if not q.statement or not q.statement.strip():
            raise HTTPException(status_code=400, detail=f"Questão {n}: enunciado vazio")
        if q.type in ("MCQ", "TRUE_FALSE"):
            valid_opts = [o for o in q.options if o.text and o.text.strip()]
            if len(valid_opts) < 2:
                raise HTTPException(status_code=400, detail=f"Questão {n}: mínimo 2 alternativas")
            correct = [o for o in valid_opts if o.is_correct]
            if len(correct) != 1:
                raise HTTPException(status_code=400, detail=f"Questão {n}: exatamente 1 alternativa correta")

    # Regras pedagógicas para AVALIACAO
    quiz_mode = quiz.mode if isinstance(quiz.mode, str) else quiz.mode.value
    if quiz_mode == "AVALIACAO":
        quiz.show_correct_immediate = False
        quiz.solutions_released = False


def effective_time_config(quiz: Quiz, assignment=None):
    """Resolve a configuração de tempo efetiva: se a turma/atribuição tiver um
    override de tempo definido, ele tem prioridade total sobre o do quiz —
    não é uma mescla campo a campo, é "ou usa tudo da turma, ou tudo do quiz".
    Retorna (mode, total_seconds, default_question_seconds, by_difficulty).
    """
    if assignment is not None and getattr(assignment, "time_mode_override", None):
        return (
            assignment.time_mode_override,
            assignment.time_total_seconds_override,
            assignment.time_default_question_seconds_override,
            assignment.time_by_difficulty_override,
        )
    mode = quiz.tempo_mode if isinstance(quiz.tempo_mode, str) else quiz.tempo_mode.value
    return (mode, quiz.time_total_seconds, quiz.time_default_question_seconds, quiz.time_by_difficulty)


def resolve_question_time(quiz: Quiz, question: QuizQuestion, assignment=None) -> int:
    if question.time_override_seconds and question.time_override_seconds > 0:
        return question.time_override_seconds
    _, _, default_question_seconds, by_difficulty = effective_time_config(quiz, assignment)
    if by_difficulty:
        # "overrides" classifica a questão só para esta turma (mesmo mecanismo
        # da sala ao vivo) — tem prioridade sobre o difficulty do quiz, que às
        # vezes é só o default "MEDIA" e nunca foi classificado de verdade.
        overrides = by_difficulty.get("overrides") or {}
        diff = overrides.get(str(question.id)) or question.difficulty
        raw = by_difficulty.get(diff) if diff else None
        if raw is not None:
            v = int(raw)
            if v > 0:
                return v
    if default_question_seconds and default_question_seconds > 0:
        return default_question_seconds
    raise HTTPException(status_code=400, detail="Sem tempo configurado para esta questão")
