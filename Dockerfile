FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir .

COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic

# Copiar arquivos de configuração de IA (YAML)
COPY configs ./configs

ENV AI_CONFIGS_DIR=/app/configs

EXPOSE 8000
