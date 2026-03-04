# Tutor Backend (FastAPI + PostgreSQL)

Backend completo e **profissional** para:
- RBAC (ADMIN / PROFESSOR / ALUNO)
- Turmas + convites + matrícula por código
- Questionários (DRAFT/PUBLISHED/CLOSED/ARCHIVED) + validação de publicação
- Atribuições (CLASS / EMAIL_LIST / PUBLIC_LINK)
- Tentativas com anti-fraude por tempo (TOTAL / PER_QUESTION / MIXED)
- Respostas (1 por questão, com integridade)
- Tutor/Chat com **guardrails de escopo** + logs (auditoria, eventos, tutor_interacoes, chat_mensagens)
- Views para dashboards

> **IA open-source:** integra com **Ollama** ou **LocalAI** via endpoint compatível OpenAI (HTTP).  
> Você pode rodar localmente (ex: `ollama serve` + `ollama pull llama3.1`).

## Como rodar (Docker)

```bash
docker compose up -d db
cp .env.example .env
docker compose run --rm api python -m app.scripts.seed
docker compose up -d api
```

Swagger: http://localhost:8000/docs

## Usuários de teste (seed)
- Admin: `admin@demo.com` / `Admin@123`
- Professor: `prof@demo.com` / `Prof@123`
- Aluno: `aluno@demo.com` / `Aluno@123`

## Tutor / IA
Configure no `.env`:
- `TUTOR_BASE_URL` (ex: `http://host.docker.internal:11434`)
- `TUTOR_MODEL` (ex: `llama3.1`)

A API chama `POST {TUTOR_BASE_URL}/v1/chat/completions`.

## Recuperação e troca de senha (com link por email)
Endpoints:
- `POST /auth/request-password-reset` `{ "email": "..." }`  
  Retorna sempre `ok`. Se SMTP não estiver configurado, o link aparece no log do container (modo dev).
- `POST /auth/reset-password` `{ "token": "...", "new_password": "..." }`
- `POST /auth/change-password` (logado) `{ "current_password": "...", "new_password": "..." }`
- `POST /auth/revoke-sessions` (logado) revoga tokens antigos (token_version)

Config no `.env`:
- `APP_PUBLIC_URL` (URL do frontend que terá a página `/reset-password`)
- SMTP (opcional) via `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, etc.

## Admin (IAM) endpoints
Requer role ADMIN:
- `GET /admin/users`
- `POST /admin/users?email=...&name=...&role=ADMIN|PROFESSOR|ALUNO&password=...&force_change_password=true`
- `POST /admin/users/{id}/set-role?role=...`
- `POST /admin/users/{id}/set-active?active=true|false` (revoga tokens)
- `POST /admin/users/{id}/reset-password?new_password=...&force_change_password=true`

## Guest (link público)
- `POST /attempts/start` aceita **sem login** apenas quando:
  - informado `public_token`
  - assignment `allow_guest=true` e `require_identity=false`
  - body deve incluir `guest_name` e `guest_email`
