from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Tutor Backend"
    ENV: str = "dev"
    SECRET_KEY: str = "change-me"

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_must_be_strong(cls, v: str) -> str:
        import os
        # Em produção, exige chave forte
        env = os.environ.get("ENV", "dev")
        if env == "prod" and (not v or v == "change-me" or len(v) < 32):
            raise ValueError("SECRET_KEY forte obrigatória em produção (mínimo 32 chars)")
        return v

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/tutor_db"
    CORS_ORIGINS: str = ""

    # Pool do Postgres
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # ── Chaves de API dos provedores de IA ──
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    HF_TOKEN: str = ""
    OLLAMA_BASE_URL: str = ""

    AI_CONFIGS_DIR: str = ""

    TUTOR_ENGINE: str = "API_DIRECT"
    AI_PROVIDER: str = ""

    # Chave mestra que cifra/decifra as API keys de IA salvas pelo admin
    # (app/utils/secrets_crypto.py). Sem isso, o admin não consegue salvar
    # chaves pela tela — precisa gerar uma vez e colocar no .env do servidor.
    SECRETS_ENCRYPTION_KEY: str = ""

    # ── RAG ──
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

    # Redis (opcional — se vazio, usa rate limit em memória)
    REDIS_URL: str = ""

    def cors_list(self) -> List[str]:
        if not self.CORS_ORIGINS:
            return ["http://localhost:5173"]
        return [x.strip() for x in self.CORS_ORIGINS.split(",") if x.strip()]


settings = Settings()
