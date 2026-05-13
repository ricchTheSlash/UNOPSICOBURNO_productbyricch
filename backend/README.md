# Backend — CGH SaaS

Backend em **Python + FastAPI** com **SQLAlchemy 2.0 async + asyncpg**,
**Alembic** para migrations, **argon2id + JWT** para auth, **slowapi** para
rate limit e **Loguru** com mascaramento de PII para logs. Banco em
**Postgres** (Supabase em produção).

## Estrutura

```
backend/
├── app/
│   ├── main.py             # FastAPI app + wiring (CORS, rate limit, routers, lifespan)
│   ├── config.py           # Settings via pydantic-settings (.env)
│   ├── database.py         # Engine async + SessionLocal
│   ├── models.py           # Modelos SQLAlchemy (Company, User, CGHProject, DailyReport, Subscription, Invite, RefreshToken)
│   ├── security.py         # argon2id + JWT encode/decode + tokens opacos
│   ├── deps.py             # get_current_user, require_role, require_active_subscription
│   ├── rate_limit.py       # slowapi Limiter
│   ├── logging_setup.py    # Loguru + masking de PII (e-mail, CPF, JWT)
│   ├── schemas/
│   │   └── auth.py         # Schemas Pydantic (Register, Login, Refresh, Invite*)
│   ├── routers/
│   │   ├── auth.py         # /auth/register, /login, /refresh, /logout
│   │   └── invites.py      # /auth/invites, /auth/invites/{token}/accept
│   └── services/
│       └── asaas.py        # Cliente HTTP do Asaas (create_customer)
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 20260513_1500_initial_schema.py
│       └── 20260513_1700_auth_invites_refresh_tokens.py
├── alembic.ini
├── requirements.txt
└── .env.example
```

## Endpoints de auth (PR #5b)

| Método | Path | Auth | Rate limit | O que faz |
|---|---|---|---|---|
| POST | `/auth/register` | público | 5/min/IP | Cria `company` + primeiro `user(role=admin)`; devolve par de tokens |
| POST | `/auth/login` | público | 10/min/IP | Troca senha por par (access + refresh) |
| POST | `/auth/refresh` | público (token no body) | — | Rotaciona: revoga refresh antigo, emite par novo |
| POST | `/auth/logout` | bearer access | — | Revoga refresh (idempotente) |
| POST | `/auth/invites` | bearer access (role=admin) | — | Cria convite p/ engineer/client; devolve token cru uma vez |
| POST | `/auth/invites/{token}/accept` | público | 10/min/IP | Destinatário define senha, vira user da company |
| GET | `/health` | público | — | `SELECT 1` no banco; 200 se OK |

Documentação interativa: `/docs` (Swagger UI), `/redoc`.

## Modelo de dados (PR #5a)

Cinco tabelas, todas com **multi-tenancy** via `company_id`:

- **`companies`** — tenant raiz. Carrega `subscription_active` (flag que o
  middleware de rotas protegidas consulta a cada request).
- **`users`** — pertencem a uma `company_id`. Papéis: `admin`, `engineer`,
  `client`. E-mail globalmente único (CITEXT, case-insensitive).
- **`cgh_projects`** — obras. Cada uma de uma `company_id`. Opcionalmente
  com `client_user_id` (investidor). Atribuição de equipe (engineers extras +
  clients) virá em `project_members` na PR #6.
- **`daily_reports`** — RDOs. 1 por projeto por dia (UNIQUE constraint).
  Sem `updated_at` propositalmente: histórico imutável.
- **`subscriptions`** — espelho local da assinatura no Asaas. Pertence à
  empresa (não a um user específico).

Mais 1 trigger genérica (`set_updated_at` usando `clock_timestamp()`) e 2
extensões (`pgcrypto`, `citext`).

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
# edite .env:
#   DATABASE_URL  -> connection string do Supabase (ou Postgres local)
#   ASAAS_API_KEY -> chave do sandbox Asaas

# 4) aplicar as migrations (cria todas as tabelas)
alembic upgrade head

# 5) subir o servidor
uvicorn app.main:app --reload

# 6) checar
curl http://localhost:8000/health
# -> {"status":"ok"}    (executa SELECT 1 no banco; 200 = conexão OK)
```

## Trabalhando com Alembic

Sempre que você mexer em `app/models.py`, gere uma nova migration:

```bash
# Compara modelos com o estado atual do banco e gera o diff SQL.
alembic revision --autogenerate -m "adiciona campo X em users"

# Revise o arquivo gerado em alembic/versions/ antes de aplicar.

# Aplica até a última migration:
alembic upgrade head

# Desfaz uma migration (rollback):
alembic downgrade -1
```

> 💡 **Autogenerate não captura tudo.** Extensões, triggers, funções PL/pgSQL
> e mudanças em CHECK constraints precisam ser escritas à mão dentro do
> arquivo de migration (use `op.execute("...")`). Sempre revise o arquivo.

## Sobre a `DATABASE_URL`

Aceitamos os 3 formatos comuns:

```
postgresql://user:pass@host:5432/db          # padrão psql/Supabase
postgres://user:pass@host:5432/db            # alias antigo (Heroku)
postgresql+asyncpg://user:pass@host:5432/db  # formato nativo SQLAlchemy
```

O código reescreve internamente para `+asyncpg` quando necessário. Você cola
a URL exatamente como o Supabase te entrega.

## Próximas fases

- **PR #5b** — Auth completa (argon2 + JWT access/refresh) + invites por
  e-mail + middleware `require_subscription` + rate limit + Loguru +
  `SECURITY.md`.
- **PR #6** — CRUD de projetos + `project_members` (atribuir engineers e
  clients a projetos específicos).
- **PR #7** — `workers` + `attendance` + criação/listagem de RDOs.
- **PR #7.5** — Endpoint `POST /subscriptions/checkout` (cria assinatura
  no Asaas).
- **PR #8** — Webhook `/webhooks/asaas` com verificação de assinatura.
- **PR #9** — Upload de fotos no Supabase Storage.
- **PR #10** — Geração de PDF do RDO (WeasyPrint).
