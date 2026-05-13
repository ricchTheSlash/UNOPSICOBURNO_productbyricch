# Backend — CGH SaaS

Backend em **Python + FastAPI** com **SQLAlchemy 2.0 async + asyncpg** e
**Alembic** para migrations. Banco em **Postgres** (Supabase em produção).

## Estrutura

```
backend/
├── app/
│   ├── main.py           # FastAPI app + /health + lifespan do engine
│   ├── config.py         # Settings carregados do .env (pydantic-settings)
│   ├── database.py       # Engine async + SessionLocal + get_db dependency
│   ├── models.py         # Modelos SQLAlchemy 2.0 (Company, User, CGHProject, DailyReport, Subscription)
│   └── services/
│       └── asaas.py      # Cliente HTTP do Asaas (create_customer)
├── alembic/
│   ├── env.py            # Runtime async-aware do Alembic
│   ├── script.py.mako    # Template usado pelo `alembic revision`
│   └── versions/
│       └── 20260513_1500_initial_schema.py
├── alembic.ini           # Config do Alembic (URL lida via env.py)
├── requirements.txt
└── .env.example
```

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
