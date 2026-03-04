from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.db.init_db import init_db
from app.routers import auth, classes, quizzes, attempts, tutor, chat, analytics, admin, global_quizzes, admin_global_quizzes
from app.db.seed import seed_mock_data
app = FastAPI(
    title=settings.APP_NAME,
    description="Backend completo para plataforma de questionários com tutor IA e RBAC.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Defina os origins que podem acessar seu backend
origins = [
    "http://172.29.32.1:5173", 
    "http://localhost:5173",   
]

# Middleware CORS corrigido
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,         
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def _startup():
    await init_db()
    await seed_mock_data()

# Incluindo routers
app.include_router(auth.router)
app.include_router(classes.router)
app.include_router(quizzes.router)
app.include_router(attempts.router)
app.include_router(tutor.router)
app.include_router(chat.router)
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(global_quizzes.router)
app.include_router(admin_global_quizzes.router)

@app.get("/health")
async def health():
    return {"ok": True, "app": settings.APP_NAME}