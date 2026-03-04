from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    # Lê variáveis do arquivo backend/.env
    # extra="ignore" permite que você tenha variáveis no .env que ainda não viraram campos aqui
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    APP_NAME: str = "Tutor Backend"
    ENV: str = "dev"
    SECRET_KEY: str = "change-me"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/tutor_db"
    CORS_ORIGINS: str = ""

    # ── Chaves de API dos provedores de IA ──
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    HF_TOKEN: str = ""
    OLLAMA_BASE_URL: str = ""

    # Diretório dos arquivos de configuração YAML (/configs)
    AI_CONFIGS_DIR: str = ""

    # ── Seleção do motor do tutor ──
    # API_DIRECT   -> usa LLM via provedores (Gemini/Groq/OpenRouter/Ollama etc.)
    # DECISION_TREE-> NÃO chama LLM; responde via regras/dicas locais
    # RAG_LLM      -> usa RAG (retriever) + LLM
    TUTOR_ENGINE: str = "API_DIRECT"  # API_DIRECT | DECISION_TREE | RAG_LLM

    # Força um provider específico do llm_providers.yaml (opcional).
    # Ex: "gemini" ou "groq". Se vazio, usa ordem do YAML/fallback.
    AI_PROVIDER: str = ""

    # ── RAG (base) ──
    RAG_CORPUS_DIR: str = ""
    RAG_MAX_CHUNKS: int = 3
    RAG_MAX_CHARS: int = 4000

    # ── Email ──
    APP_PUBLIC_URL: str = "http://localhost:3000"
    EMAIL_FROM: str = "no-reply@demo.com"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_TLS: bool = True
    PASSWORD_RESET_TTL_MIN: int = 30

    # ── Rate limits ──
    RL_LOGIN_PER_MIN: int = 10
    RL_TUTOR_PER_MIN: int = 20
    RL_ATTEMPT_START_PER_MIN: int = 10

    def cors_list(self) -> List[str]:
        if not self.CORS_ORIGINS:
            return []
        return [x.strip() for x in self.CORS_ORIGINS.split(",") if x.strip()]


settings = Settings()
