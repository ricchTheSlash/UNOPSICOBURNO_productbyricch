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
│   ├── models.py           # Modelos SQLAlchemy (Company, User, CGHProject, ProjectMember, DailyReport, Worker, Attendance, Subscription, Invite, RefreshToken)
│   ├── security.py         # argon2id + JWT encode/decode + tokens opacos
│   ├── deps.py             # get_current_user, require_role, require_active_subscription, require_subscription_and_role
│   ├── access.py           # Helpers de acesso a projeto (compartilhados entre routers)
│   ├── rate_limit.py       # slowapi Limiter
│   ├── logging_setup.py    # Loguru + masking de PII (e-mail, CPF, JWT)
│   ├── schemas/
│   │   ├── auth.py         # Register, Login, Refresh, Invite*
│   │   ├── projects.py     # ProjectCreate/Update/Response, Member*
│   │   ├── workers.py      # WorkerCreate/Update/Response
│   │   ├── reports.py      # RDOCreate/Response/Detail, Attendance*
│   │   └── subscriptions.py# CheckoutRequest/Response, SubscriptionResponse
│   ├── routers/
│   │   ├── auth.py         # /auth/register, /login, /refresh, /logout
│   │   ├── invites.py      # /auth/invites, /auth/invites/{token}/accept
│   │   ├── projects.py     # /projects CRUD + /projects/{id}/members
│   │   ├── workers.py      # /workers CRUD
│   │   ├── reports.py      # /projects/{id}/reports (RDO) + attendance
│   │   └── subscriptions.py# /subscriptions/checkout + /current
│   └── services/
│       ├── asaas.py        # Cliente Asaas (create_customer, create_subscription, payments)
│       └── email.py        # EmailProvider (Console + Resend) + send_invite_email
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 20260513_1500_initial_schema.py
│       ├── 20260513_1700_auth_invites_refresh_tokens.py
│       ├── 20260513_1800_project_members.py
│       └── 20260514_2100_workers_attendance.py
├── alembic.ini
├── requirements.txt
└── .env.example
```

## Endpoints

### Auth + invites (PR #5b/#5c)

| Método | Path | Auth | Rate limit | O que faz |
|---|---|---|---|---|
| POST | `/auth/register` | público | 5/min/IP | Cria `company` + primeiro `user(role=admin)`; devolve par de tokens |
| POST | `/auth/login` | público | 10/min/IP | Troca senha por par (access + refresh) |
| POST | `/auth/refresh` | público (token no body) | — | Rotaciona: revoga refresh antigo, emite par novo |
| POST | `/auth/logout` | bearer access | — | Revoga refresh (idempotente) |
| POST | `/auth/invites` | bearer (admin) | — | Cria convite; dispara e-mail; em dev devolve token+accept_url |
| POST | `/auth/invites/{token}/accept` | público | 10/min/IP | Destinatário define senha, vira user da company |

### Projetos (PR #6)

Todas as rotas requerem **assinatura ativa** (`require_active_subscription`,
402 se inativa) e fazem **tenant isolation** automático (filtra por `company_id`).

| Método | Path | Auth | O que faz |
|---|---|---|---|
| POST | `/projects` | bearer (admin) | Cria projeto na company do admin |
| GET | `/projects` | bearer | Lista: admin vê tudo da company; engineer/client só onde é member |
| GET | `/projects/{id}` | bearer (com acesso) | Detalhe do projeto. 404 se cross-tenant ou não-member |
| PATCH | `/projects/{id}` | bearer (admin) | Update parcial (só admin) |
| DELETE | `/projects/{id}` | bearer (admin) | Hard delete (CASCADE em RDOs e members) |
| GET | `/projects/{id}/members` | bearer (com acesso) | Lista members do projeto |
| POST | `/projects/{id}/members` | bearer (admin) | Atribui user (engineer/client) ao projeto |
| DELETE | `/projects/{id}/members/{user_id}` | bearer (admin) | Remove user (idempotente) |

### Workers — efetivo de campo (PR #7)

Roster da empresa. `admin` e `engineer` gerenciam; `client` não acessa (403).
Todas exigem assinatura ativa.

| Método | Path | Auth | O que faz |
|---|---|---|---|
| POST | `/workers` | admin/engineer | Cadastra worker no roster da company |
| GET | `/workers` | admin/engineer | Lista roster (`?include_inactive=true` inclui desativados) |
| GET | `/workers/{id}` | admin/engineer | Detalhe |
| PATCH | `/workers/{id}` | admin/engineer | Update parcial (inclui `is_active` p/ (des)ativar) |
| DELETE | `/workers/{id}` | admin/engineer | Hard delete; 409 se tiver presença (sugere desativar) |

### RDO (Relatório Diário de Obra) + presença (PR #7)

Aninhado sob `/projects/{project_id}/reports`. Requer acesso à obra.
O RDO é **imutável** (sem PATCH). Presença é dado operacional corrigível.

| Método | Path | Auth | O que faz |
|---|---|---|---|
| POST | `/projects/{pid}/reports` | admin/engineer com acesso | Cria RDO (presença opcional embutida); 409 se já houver RDO na data |
| GET | `/projects/{pid}/reports` | com acesso (inclui client) | Lista RDOs da obra |
| GET | `/projects/{pid}/reports/{id}` | com acesso | Detalhe do RDO + presença |
| DELETE | `/projects/{pid}/reports/{id}` | admin | Remove RDO mal-lançado (CASCADE na presença) |
| POST | `/projects/{pid}/reports/{id}/attendance` | admin/engineer com acesso | Adiciona presença de 1 worker |
| DELETE | `/projects/{pid}/reports/{id}/attendance/{worker_id}` | admin/engineer com acesso | Remove presença (idempotente) |

### Assinatura / checkout (PR #7.5)

Usa `require_role("admin")` **sem** checagem de assinatura (a empresa está
pagando justamente para ativá-la — exigir assinatura aqui seria deadlock).

| Método | Path | Auth | O que faz |
|---|---|---|---|
| POST | `/subscriptions/checkout` | admin | Cria a assinatura no Asaas e devolve o link de pagamento (`payment_url`) |
| GET | `/subscriptions/current` | admin | Assinatura corrente da empresa (404 se nunca houve checkout) |

O checkout **não** liga `companies.subscription_active` — isso só acontece
quando o webhook do Asaas confirmar o pagamento (PR #8). Checkout cria a
intenção de pagar; a confirmação é assíncrona. Chamadas repetidas reusam a
assinatura existente (idempotente), sem duplicar no Asaas.

### Outros

| Método | Path | Auth | O que faz |
|---|---|---|---|
| GET | `/health` | público | `SELECT 1` no banco; 200 se OK |

Documentação interativa: `/docs` (Swagger UI), `/redoc`.

## Modelo de dados (PR #5a)

Cinco tabelas, todas com **multi-tenancy** via `company_id`:

- **`companies`** — tenant raiz. Carrega `subscription_active` (flag que o
  middleware de rotas protegidas consulta a cada request).
- **`users`** — pertencem a uma `company_id`. Papéis: `admin`, `engineer`,
  `client`. E-mail globalmente único (CITEXT, case-insensitive).
- **`cgh_projects`** — obras. Cada uma pertence a uma `company_id`. Members
  (engineers e clients atribuídos) ficam em `project_members` (N:N).
- **`project_members`** — quem participa de qual obra. Admins enxergam tudo
  da company; engineers/clients só projetos onde estão como member.
- **`daily_reports`** — RDOs. 1 por projeto por dia (UNIQUE constraint).
  Sem `updated_at` propositalmente: histórico imutável.
- **`workers`** — efetivo de campo (NÃO são users; não logam). Pertencem a uma
  `company_id`. `employment_type` = `clt`/`diarista`. Soft-delete via `is_active`.
- **`attendance`** — presença de um worker num RDO. FK `daily_report_id`
  CASCADE (some com o RDO); FK `worker_id` RESTRICT (preserva o worker).
  UNIQUE(daily_report_id, worker_id).
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

## Envio de e-mail dos convites (PR #5c)

A rota `POST /auth/invites` dispara um e-mail para o destinatário com o
link de aceitação. Provider configurável via `EMAIL_PROVIDER` no `.env`:

| Provider | O que faz | Quando usar |
|---|---|---|
| `console` (default) | Loga o conteúdo do e-mail no console + `logs/app.log` | Dev local: testa sem precisar de inbox |
| `resend` | Envia via API do [Resend](https://resend.com) | Staging / produção |

**Setup do Resend (3 passos, 5 minutos):**

1. Crie conta grátis em https://resend.com (free tier: 100/dia, 3000/mês).
2. Gere uma API key em **Settings → API Keys**.
3. No `.env`:
   ```
   EMAIL_PROVIDER=resend
   RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxx
   RESEND_FROM=CGH SaaS <onboarding@resend.dev>   # dev/teste
   # Em produção, troque por um endereço de domínio verificado.
   ```

**Em desenvolvimento** (`APP_ENV=development`) a resposta de `POST /auth/invites`
inclui também `token` e `accept_url` no body — útil pra testar sem inbox.
**Em produção** (`APP_ENV=production`), esses campos saem como `null`: o
e-mail é a única forma de o destinatário obter o link.

## Próximas fases

- **PR #8** — Webhook `/webhooks/asaas` com verificação de assinatura
  (liga `companies.subscription_active` quando o pagamento é confirmado).
- **PR #9** — Upload de fotos no Supabase Storage.
- **PR #10** — Geração de PDF do RDO (WeasyPrint).
