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


def resolve_question_time(quiz: Quiz, question: QuizQuestion) -> int:
    if question.time_override_seconds and question.time_override_seconds > 0:
        return question.time_override_seconds
    if quiz.time_by_difficulty and question.difficulty in quiz.time_by_difficulty:
        v = int(quiz.time_by_difficulty[question.difficulty])
        if v > 0:
            return v
    if quiz.time_default_question_seconds and quiz.time_default_question_seconds > 0:
        return quiz.time_default_question_seconds
    raise HTTPException(status_code=400, detail="Sem tempo configurado para esta questão")
