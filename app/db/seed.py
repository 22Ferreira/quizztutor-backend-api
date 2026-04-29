import secrets
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from passlib.context import CryptContext

from app.db.session import AsyncSessionLocal
from app.models.user import User, UserRole
from app.models.classroom import Class
from app.models.quiz import (
    Quiz,
    QuizStatus,
    TutorConfig,
    TutorScope,
    QuizQuestion,
    QuizOption,
)
from app.models.global_quiz import GlobalQuizRequest, GlobalQuizRequestStatus

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (title or "").strip().lower()).strip("-")
    return s[:40] if s else "quiz"


def _make_slug(title: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    return f"{_slugify(title)}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{suffix}"


async def seed_mock_data():
    async with AsyncSessionLocal() as session:
        # ─────────────────────────────────────────────
        # 0) ADMIN padrão (para aprovar global)
        # ─────────────────────────────────────────────
        email_admin = "admin@local.test"
        admin = await session.scalar(select(User).where(User.email == email_admin))
        if not admin:
            admin = User(
                email=email_admin,
                name="Admin do Sistema",
                password_hash=pwd_context.hash("12345678"),
                role=UserRole.ADMIN,
                active=True,
                must_change_password=False,
            )
            session.add(admin)
            await session.flush()  # pega id sem commit

        # ─────────────────────────────────────────────
        # 1) Professor padrão
        # ─────────────────────────────────────────────
        email_prof = "prof.paralela@local.test"
        professor = await session.scalar(select(User).where(User.email == email_prof))
        if not professor:
            professor = User(
                email=email_prof,
                name="Professor Paralela",
                password_hash=pwd_context.hash("12345678"),
                role=UserRole.PROFESSOR,
                active=True,
                must_change_password=False,
            )
            session.add(professor)
            await session.flush()

        # ─────────────────────────────────────────────
        # 2) Turma Programação Paralela
        # ─────────────────────────────────────────────
        code = "PARALELA-2026"
        turma = await session.scalar(select(Class).where(Class.code_entry == code))
        if not turma:
            turma = Class(
                professor_id=professor.id,
                name="Programação Paralela",
                discipline="Programação Paralela",
                code_entry=code,
                active=True,
            )
            session.add(turma)

        # ─────────────────────────────────────────────
        # 3) Quizzes do professor (exemplo)
        # ─────────────────────────────────────────────
        quizzes_prof = [
            ("Quiz 01 — Fundamentos", "Concorrência vs paralelismo; speedup; Amdahl."),
            ("Quiz 02 — Threads e Sincronização", "Mutex, semáforos, deadlock, starvation."),
            ("Quiz 03 — OpenMP", "Diretivas, schedule, reduction, critical."),
        ]

        for title, desc in quizzes_prof:
            q = await session.scalar(
                select(Quiz).where(Quiz.professor_id == professor.id, Quiz.title == title)
            )

            if not q:
                q = Quiz(
                                        share_code=secrets.token_hex(4).upper(),
                    professor_id=professor.id,
                    title=title,
                    description=desc,
                    status=QuizStatus.PUBLISHED,
                    tutor_active=True,
                    chat_active=True,
                )
                session.add(q)
                await session.flush()
            else:
                q.status = QuizStatus.PUBLISHED
                q.tutor_active = True
                q.chat_active = True

            tc = await session.scalar(select(TutorConfig).where(TutorConfig.quiz_id == q.id))
            if not tc:
                tc = TutorConfig(
                    quiz_id=q.id,
                    enabled=True,
                    scope=TutorScope.SOMENTE_QUESTAO_ATUAL,
                    allow_out_of_scope=False,
                    allow_explanation=True,
                    allow_hints=True,
                )
                session.add(tc)

            req = await session.scalar(select(GlobalQuizRequest).where(GlobalQuizRequest.quiz_id == q.id))
            if not req:
                req = GlobalQuizRequest(
                    quiz_id=q.id,
                    requested_by=professor.id,
                    status=GlobalQuizRequestStatus.APPROVED,
                    is_active=True,
                    approved_public_slug=_make_slug(q.title),
                    reviewed_by=admin.id,
                    reviewed_at=datetime.now(timezone.utc),
                    review_note="Seed: aprovado automaticamente",
                )
                session.add(req)
            else:
                req.status = GlobalQuizRequestStatus.APPROVED
                req.is_active = True
                if not getattr(req, "approved_public_slug", None):
                    req.approved_public_slug = _make_slug(q.title)
                req.reviewed_by = admin.id
                req.reviewed_at = datetime.now(timezone.utc)
                req.review_note = "Seed: re-aprovado automaticamente"

            existing_any = await session.scalar(select(QuizQuestion).where(QuizQuestion.quiz_id == q.id))
            if not existing_any:
                q1 = QuizQuestion(
                    quiz_id=q.id,
                    order=1,
                    statement="Qual a principal diferença entre concorrência e paralelismo?",
                    explanation="Concorrência lida com múltiplas tarefas; paralelismo executa simultaneamente.",
                    difficulty="MEDIA",
                    points=1,
                    topic="Fundamentos",
                )
                session.add(q1)
                await session.flush()

                session.add_all(
                    [
                        QuizOption(question_id=q1.id, order=1, text="São a mesma coisa", is_correct=False),
                        QuizOption(
                            question_id=q1.id,
                            order=2,
                            text="Paralelismo executa simultaneamente em múltiplos núcleos",
                            is_correct=True,
                        ),
                        QuizOption(question_id=q1.id, order=3, text="Concorrência só existe em GPU", is_correct=False),
                        QuizOption(question_id=q1.id, order=4, text="Paralelismo é apenas teórico", is_correct=False),
                    ]
                )

                q2 = QuizQuestion(
                    quiz_id=q.id,
                    order=2,
                    statement="A Lei de Amdahl descreve:",
                    explanation="O limite do speedup paralelo depende da fração sequencial do programa.",
                    difficulty="MEDIA",
                    points=1,
                    topic="Speedup",
                )
                session.add(q2)
                await session.flush()

                session.add_all(
                    [
                        QuizOption(question_id=q2.id, order=1, text="Velocidade da CPU", is_correct=False),
                        QuizOption(question_id=q2.id, order=2, text="Limite do speedup paralelo", is_correct=True),
                        QuizOption(question_id=q2.id, order=3, text="Escalonamento de processos", is_correct=False),
                        QuizOption(question_id=q2.id, order=4, text="Memória cache", is_correct=False),
                    ]
                )

        # ─────────────────────────────────────────────
        # 4) 10 QUIZZES GLOBAIS (todos podem ver)
        #    - cada um com 2 questões MCQ (4 opções)
        # ─────────────────────────────────────────────
        global_quiz_templates = [
            ("Global 01 — Introdução", "Conceitos iniciais: concorrência, paralelismo, throughput."),
            ("Global 02 — Processos vs Threads", "Diferenças, custo de troca de contexto, casos de uso."),
            ("Global 03 — Sincronização", "Mutex, semáforos, monitores, condições de corrida."),
            ("Global 04 — Deadlock", "Condições de Coffman, prevenção, detecção, recuperação."),
            ("Global 05 — Escalonamento", "Políticas, fairness, starvation, prioridades."),
            ("Global 06 — Memória Compartilhada", "Região crítica, visibilidade, barreiras e ordering."),
            ("Global 07 — OpenMP Básico", "parallel, for, schedule, reduction."),
            ("Global 08 — OpenMP Avançado", "critical, atomic, barrier, sections, tasks."),
            ("Global 09 — Speedup e Amdahl", "Limites teóricos, gargalos, otimização."),
            ("Global 10 — Boas Práticas", "Debug concorrente, testes, observabilidade, performance."),
        ]

        for i, (t, d) in enumerate(global_quiz_templates, start=1):
            title = f"Quiz {t}"
            desc = d

            qg = await session.scalar(
                select(Quiz).where(Quiz.professor_id == professor.id, Quiz.title == title)
            )

            if not qg:
                qg = Quiz(
                                        share_code=secrets.token_hex(4).upper(),
                    professor_id=professor.id,
                    title=title,
                    description=desc,
                    status=QuizStatus.PUBLISHED,
                    tutor_active=True,
                    chat_active=True,
                )
                session.add(qg)
                await session.flush()
            else:
                qg.status = QuizStatus.PUBLISHED
                qg.tutor_active = True
                qg.chat_active = True

            # TutorConfig
            tcg = await session.scalar(select(TutorConfig).where(TutorConfig.quiz_id == qg.id))
            if not tcg:
                tcg = TutorConfig(
                    quiz_id=qg.id,
                    enabled=True,
                    scope=TutorScope.SOMENTE_QUESTAO_ATUAL,
                    allow_out_of_scope=False,
                    allow_explanation=True,
                    allow_hints=True,
                )
                session.add(tcg)

            # GlobalQuizRequest APPROVED
            reqg = await session.scalar(select(GlobalQuizRequest).where(GlobalQuizRequest.quiz_id == qg.id))
            if not reqg:
                reqg = GlobalQuizRequest(
                    quiz_id=qg.id,
                    requested_by=professor.id,
                    status=GlobalQuizRequestStatus.APPROVED,
                    is_active=True,
                    approved_public_slug=_make_slug(qg.title),
                    reviewed_by=admin.id,
                    reviewed_at=datetime.now(timezone.utc),
                    review_note="Seed: global aprovado automaticamente",
                )
                session.add(reqg)
            else:
                reqg.status = GlobalQuizRequestStatus.APPROVED
                reqg.is_active = True
                if not getattr(reqg, "approved_public_slug", None):
                    reqg.approved_public_slug = _make_slug(qg.title)
                reqg.reviewed_by = admin.id
                reqg.reviewed_at = datetime.now(timezone.utc)
                reqg.review_note = "Seed: global re-aprovado automaticamente"

            # Questões mínimas (2) se não existir nenhuma
            existing_any = await session.scalar(select(QuizQuestion).where(QuizQuestion.quiz_id == qg.id))
            if not existing_any:
                # Q1
                qq1 = QuizQuestion(
                    quiz_id=qg.id,
                    order=1,
                    statement="O que caracteriza paralelismo em um programa?",
                    explanation="Paralelismo implica executar partes simultaneamente (ex.: múltiplos núcleos).",
                    difficulty="MEDIA",
                    points=1,
                    topic="Fundamentos",
                )
                session.add(qq1)
                await session.flush()
                session.add_all(
                    [
                        QuizOption(question_id=qq1.id, order=1, text="Executar tarefas uma após a outra", is_correct=False),
                        QuizOption(question_id=qq1.id, order=2, text="Executar simultaneamente", is_correct=True),
                        QuizOption(question_id=qq1.id, order=3, text="Somente usar GPU", is_correct=False),
                        QuizOption(question_id=qq1.id, order=4, text="Somente usar cache", is_correct=False),
                    ]
                )

                # Q2
                qq2 = QuizQuestion(
                    quiz_id=qg.id,
                    order=2,
                    statement="Qual é uma causa comum de race condition?",
                    explanation="Acesso concorrente ao mesmo dado sem sincronização apropriada.",
                    difficulty="MEDIA",
                    points=1,
                    topic="Sincronização",
                )
                session.add(qq2)
                await session.flush()
                session.add_all(
                    [
                        QuizOption(question_id=qq2.id, order=1, text="Variável compartilhada sem lock", is_correct=True),
                        QuizOption(question_id=qq2.id, order=2, text="Uso de SSD", is_correct=False),
                        QuizOption(question_id=qq2.id, order=3, text="Uso de IPv6", is_correct=False),
                        QuizOption(question_id=qq2.id, order=4, text="Código em Python", is_correct=False),
                    ]
                )

        # ─────────────────────────────────────────────
        # 5) QUIZ GLOBAL CAD (do sti.zip) - 15 questões
        # ─────────────────────────────────────────────
        cad_title = "Quiz CAD — Global"
        cad_desc = "Introdução à CAD, Histórico/Evolução e Ferramentas (base sti.zip)."

        cad_quiz = await session.scalar(
            select(Quiz).where(Quiz.professor_id == professor.id, Quiz.title == cad_title)
        )
        if not cad_quiz:
            cad_quiz = Quiz(
                                    share_code=secrets.token_hex(4).upper(),
                    professor_id=professor.id,
                title=cad_title,
                description=cad_desc,
                status=QuizStatus.PUBLISHED,
                tutor_active=True,
                chat_active=True,
            )
            session.add(cad_quiz)
            await session.flush()
        else:
            cad_quiz.status = QuizStatus.PUBLISHED
            cad_quiz.tutor_active = True
            cad_quiz.chat_active = True

        cad_tc = await session.scalar(select(TutorConfig).where(TutorConfig.quiz_id == cad_quiz.id))
        if not cad_tc:
            cad_tc = TutorConfig(
                quiz_id=cad_quiz.id,
                enabled=True,
                scope=TutorScope.SOMENTE_QUESTAO_ATUAL,
                allow_out_of_scope=False,
                allow_explanation=True,
                allow_hints=True,
            )
            session.add(cad_tc)

        cad_req = await session.scalar(select(GlobalQuizRequest).where(GlobalQuizRequest.quiz_id == cad_quiz.id))
        if not cad_req:
            cad_req = GlobalQuizRequest(
                quiz_id=cad_quiz.id,
                requested_by=professor.id,
                status=GlobalQuizRequestStatus.APPROVED,
                is_active=True,
                approved_public_slug=_make_slug(cad_quiz.title),
                reviewed_by=admin.id,
                reviewed_at=datetime.now(timezone.utc),
                review_note="Seed: CAD aprovado automaticamente",
            )
            session.add(cad_req)
        else:
            cad_req.status = GlobalQuizRequestStatus.APPROVED
            cad_req.is_active = True
            if not getattr(cad_req, "approved_public_slug", None):
                cad_req.approved_public_slug = _make_slug(cad_quiz.title)
            cad_req.reviewed_by = admin.id
            cad_req.reviewed_at = datetime.now(timezone.utc)
            cad_req.review_note = "Seed: CAD re-aprovado automaticamente"

        existing_cad_any = await session.scalar(select(QuizQuestion).where(QuizQuestion.quiz_id == cad_quiz.id))
        if not existing_cad_any:
            cad_questions = [
                (
                    "O que significa a sigla CAD?",
                    "CAD significa Computer Aided Design (Desenho Assistido por Computador).",
                    "MEDIA",
                    "Introdução à CAD",
                    1,
                    [
                        ("Computer Aided Design", True),
                        ("Computer Automatic Drawing", False),
                        ("Computer Assisted Data", False),
                        ("Control and Design", False),
                        ("Calculation and Design", False),
                    ],
                ),
                (
                    "Qual é a principal função do CAD?",
                    "A função principal é criar/editar projetos e desenhos técnicos (2D/3D).",
                    "FACIL",
                    "Introdução à CAD",
                    2,
                    [
                        ("Criar projetos e desenhos técnicos", True),
                        ("Editar vídeos", False),
                        ("Criar planilhas", False),
                        ("Programar sistemas", False),
                        ("Criar animações 3D apenas", False),
                    ],
                ),
                (
                    "Qual dessas áreas utiliza CAD com frequência?",
                    "Engenharia usa CAD para desenho técnico, modelagem e documentação.",
                    "FACIL",
                    "Introdução à CAD",
                    3,
                    [
                        ("Engenharia", True),
                        ("Música", False),
                        ("Gastronomia", False),
                        ("Psicologia", False),
                        ("Teatro", False),
                    ],
                ),
                (
                    "CAD é usado principalmente para:",
                    "CAD é usado para desenho técnico e modelagem de peças/projetos.",
                    "FACIL",
                    "Introdução à CAD",
                    4,
                    [
                        ("Desenho técnico e modelagem", True),
                        ("Edição de fotos", False),
                        ("Redes sociais", False),
                        ("Criação de documentos", False),
                        ("Jogos online", False),
                    ],
                ),
                (
                    "O CAD pode ser usado para projetos:",
                    "Ferramentas CAD suportam desenhos 2D e modelos 3D.",
                    "FACIL",
                    "Introdução à CAD",
                    5,
                    [
                        ("2D e 3D", True),
                        ("Apenas 2D", False),
                        ("Apenas 3D", False),
                        ("Apenas texto", False),
                        ("Apenas áudio", False),
                    ],
                ),
                (
                    "Em que década o CAD começou a ser desenvolvido?",
                    "Os primeiros trabalhos de CAD surgiram na década de 1960.",
                    "MEDIA",
                    "Histórico e Evolução",
                    6,
                    [
                        ("1960", True),
                        ("1920", False),
                        ("1940", False),
                        ("1980", False),
                        ("2000", False),
                    ],
                ),
                (
                    "Um dos primeiros sistemas CAD foi criado por:",
                    "Ivan Sutherland foi um dos pioneiros do CAD.",
                    "FACIL",
                    "Histórico e Evolução",
                    7,
                    [
                        ("Ivan Sutherland", True),
                        ("Bill Gates", False),
                        ("Steve Jobs", False),
                        ("Alan Turing", False),
                        ("Elon Musk", False),
                    ],
                ),
                (
                    "Qual foi o nome do projeto pioneiro de CAD criado por Ivan Sutherland?",
                    "Sketchpad é considerado um marco pioneiro em CAD.",
                    "MEDIA",
                    "Histórico e Evolução",
                    8,
                    [
                        ("Sketchpad", True),
                        ("AutoCAD", False),
                        ("SolidWorks", False),
                        ("CorelDraw", False),
                        ("Paint", False),
                    ],
                ),
                (
                    "O CAD se popularizou principalmente por causa:",
                    "O avanço do hardware/software de computadores impulsionou o CAD.",
                    "FACIL",
                    "Histórico e Evolução",
                    9,
                    [
                        ("Do avanço dos computadores", True),
                        ("Da internet", False),
                        ("Do rádio", False),
                        ("Da televisão", False),
                        ("Dos celulares", False),
                    ],
                ),
                (
                    "A evolução do CAD permitiu:",
                    "A evolução trouxe modelagem 3D, simulações e análise.",
                    "MEDIA",
                    "Histórico e Evolução",
                    10,
                    [
                        ("Modelagem 3D e simulações", True),
                        ("Apenas desenho manual", False),
                        ("Apenas texto", False),
                        ("Apenas cálculo financeiro", False),
                        ("Apenas edição de imagem", False),
                    ],
                ),
                (
                    "Qual é um software CAD muito conhecido?",
                    "AutoCAD é um dos softwares CAD mais populares.",
                    "FACIL",
                    "Ferramentas Paralelas",
                    11,
                    [
                        ("AutoCAD", True),
                        ("Excel", False),
                        ("Word", False),
                        ("Photoshop", False),
                        ("WhatsApp", False),
                    ],
                ),
                (
                    "Qual é uma característica do SolidWorks?",
                    "SolidWorks é conhecido por modelagem paramétrica 3D.",
                    "MEDIA",
                    "Ferramentas Paralelas",
                    12,
                    [
                        ("Modelagem paramétrica 3D", True),
                        ("Apenas desenho 2D", False),
                        ("Editor de áudio", False),
                        ("Navegador web", False),
                        ("Sistema operacional", False),
                    ],
                ),
                (
                    "Qual dessas ferramentas é usada para modelagem 3D?",
                    "Fusion 360 é usado para modelagem 3D e CAD/CAM.",
                    "MEDIA",
                    "Ferramentas Paralelas",
                    13,
                    [
                        ("Fusion 360", True),
                        ("PowerPoint", False),
                        ("Notepad", False),
                        ("VLC", False),
                        ("Spotify", False),
                    ],
                ),
                (
                    "Qual dessas opções é um software de CAD livre?",
                    "FreeCAD é uma opção livre/open-source para CAD.",
                    "MEDIA",
                    "Ferramentas Paralelas",
                    14,
                    [
                        ("FreeCAD", True),
                        ("AutoCAD", False),
                        ("SolidWorks", False),
                        ("Fusion 360", False),
                        ("CATIA", False),
                    ],
                ),
                (
                    "Ferramentas CAD permitem:",
                    "CAD permite criar e editar projetos técnicos e documentação.",
                    "MEDIA",
                    "Ferramentas Paralelas",
                    15,
                    [
                        ("Criação e edição de projetos técnicos", True),
                        ("Criação de músicas", False),
                        ("Criação de filmes", False),
                        ("Criação de redes sociais", False),
                        ("Criação de jogos apenas", False),
                    ],
                ),
            ]

            for statement, explanation, difficulty, topic, order, options in cad_questions:
                qq = QuizQuestion(
                    quiz_id=cad_quiz.id,
                    order=order,
                    statement=statement,
                    explanation=explanation,
                    difficulty=difficulty,
                    points=1,
                    topic=topic,
                )
                session.add(qq)
                await session.flush()

                for opt_order, (txt, is_ok) in enumerate(options, start=1):
                    session.add(
                        QuizOption(
                            question_id=qq.id,
                            order=opt_order,
                            text=txt,
                            is_correct=bool(is_ok),
                        )
                    )

        await session.commit()