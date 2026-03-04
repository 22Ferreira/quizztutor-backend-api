# Tutor Fullstack (corrigido)

Este pacote está ajustado para funcionar no Windows/WSL **sem build docker do Node/Python** (evita erro de credenciais do Docker Hub).
O Docker sobe apenas o Postgres em **localhost:5434**.

## Subir banco (Docker)
```powershell
docker compose up -d db
```

## Rodar backend (sem Docker)
```powershell
cd backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Rodar seed (cria 3 usuários + quiz)
```powershell
cd backend
venv\Scripts\Activate.ps1
python -m app.scripts.seed
```

## Rodar frontend (sem Docker)
```powershell
cd frontend
npm install
npm run dev
```

## URLs
- Front: http://localhost:5173
- Swagger: http://localhost:8000/docs

## Usuários seed
- admin@demo.com / Admin@123
- prof@demo.com / Prof@123
- aluno@demo.com / Aluno@123

## Scripts (Windows)
- `start_dev_windows.ps1` (sobe db + abre terminais para api e web)
- `seed_windows.ps1` (roda seed)

## (Opcional) Full Docker
Se você resolver `docker login`/credenciais, pode usar:
```powershell
docker compose -f docker-compose.full.yml up --build
```
