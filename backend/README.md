# Backend — CGH SaaS

Backend em **Python + FastAPI**. Banco em **Postgres** (Supabase).

## Estrutura

```
backend/
├── app/
│   ├── main.py           # FastAPI app + /health + lifespan do pool
│   ├── config.py         # Settings carregados do .env (pydantic-settings)
│   ├── database.py       # Pool psycopg + helper get_conn()
│   └── services/
│       └── asaas.py      # Cliente HTTP do Asaas (create_customer)
├── migrations/
│   └── 001_init.sql      # Schema das 4 tabelas (users, cgh_projects, daily_reports, subscriptions)
├── requirements.txt
└── .env.example
```

## Como rodar localmente

```bash
cd backend

# 1) ambiente virtual
python -m venv venv
source venv/bin/activate          # Linux/Mac
# .\venv\Scripts\activate         # Windows

# 2) dependências
pip install -r requirements.txt

# 3) variáveis de ambiente
cp .env.example .env
# edite .env com a DATABASE_URL real do Supabase e a chave do Asaas (sandbox)

# 4) aplicar schema no banco (precisa do psql instalado, ou rode via Supabase SQL Editor)
psql "$DATABASE_URL" -f migrations/001_init.sql

# 5) subir o servidor
uvicorn app.main:app --reload

# 6) checar
curl http://localhost:8000/health
# -> {"status":"ok"}
```

## Próximas fases (fora do escopo desta entrega)

- Autenticação JWT (`/auth/register`, `/auth/login`) + hash de senha.
- Middleware que bloqueia rotas se `users.subscription_active = false`.
- CRUD de projetos e RDOs.
- Endpoint `/webhooks/asaas` que atualiza `subscriptions.status` e a flag de assinatura.
- Frontend React + Tailwind.
- Script de deploy (Nginx + systemd) para a VPS Hostinger.
