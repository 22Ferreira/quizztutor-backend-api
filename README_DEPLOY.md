# Como rodar o projeto (Dev e Prod)

## Desenvolvimento

```bash
# 1. Copie o arquivo de exemplo e preencha suas chaves de IA
cp .env.dev.example .env.dev

# 2. Suba os containers (Postgres + Redis + Backend com hot reload)
docker compose up --build

# Backend disponível em: http://localhost:8000
# Docs Swagger:          http://localhost:8000/docs
```

O seed de dados de teste roda automaticamente em `ENV=dev`.

---

## Produção

```bash
# 1. Copie e configure o env de produção
cp .env.prod.example .env.prod
# Edite .env.prod:
#   - SECRET_KEY: gere com → python -c "import secrets; print(secrets.token_hex(32))"
#   - DATABASE_URL: sua senha real
#   - CORS_ORIGINS: seu domínio
#   - REDIS_URL: redis://redis:6379/0 (já configurado no compose)
#   - SMTP_*: suas credenciais de email

# 2. Suba em produção (4 workers Gunicorn + Redis)
docker compose -f docker-compose.prod.yml up -d --build

# 3. Rodar migrations antes de subir
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
```

Em produção:
- `/docs` e `/redoc` ficam **desabilitados** automaticamente
- Seed de dados **não roda** (apenas em `ENV=dev`)
- Rate limit usa **Redis** (funciona com múltiplos workers)
- Email usa **aiosmtplib** (não bloqueia o event loop)

---

## Variáveis importantes

| Variável | Dev | Prod |
|----------|-----|------|
| `ENV` | `dev` | `prod` |
| `SECRET_KEY` | qualquer string | **mínimo 32 chars, aleatória** |
| `REDIS_URL` | vazio (usa memória) | `redis://redis:6379/0` |
| `CORS_ORIGINS` | `http://localhost:5173` | seus domínios reais |
| `DB_POOL_SIZE` | 5 | 10 (ajuste por nº de workers) |

---

## Escala (centenas de acessos simultâneos)

- Aumente `--workers` no `docker-compose.prod.yml` (recomendado: `2 * núcleos + 1`)
- Ajuste `DB_POOL_SIZE` → `workers * pool_size <= max_connections do Postgres`
  - Ex: 4 workers × pool_size 10 = 40 conexões simultâneas
- Redis é obrigatório quando há mais de 1 worker (rate limit)
