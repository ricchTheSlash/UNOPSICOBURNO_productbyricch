# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CGH SaaS — multi-tenant backend for managing the construction of small hydroelectric plants (CGHs). Stack: **FastAPI + SQLAlchemy 2.0 async + asyncpg + Alembic + Postgres** (Supabase in prod) + **Asaas** (Brazilian payments). React frontend is planned; `frontend/` is currently empty.

Source of truth for setup/endpoints/data model: **`backend/README.md`**. Security posture and pentest checklist: **`SECURITY.md`** at repo root. Don't restate them — point users there.

## Common commands

All run from `backend/` after `source venv/bin/activate`.

```bash
# Initial setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill DATABASE_URL, ASAAS_API_KEY, JWT_SECRET_KEY

# Run server with auto-reload
uvicorn app.main:app --reload

# Migrations
alembic upgrade head                              # apply all
alembic downgrade -1                              # rollback one
alembic revision --autogenerate -m "message"      # diff models vs DB

# Health probe (executes SELECT 1; 200 only if DB reachable)
curl http://localhost:8000/health
```

Interactive API playground: `http://localhost:8000/docs` (Swagger), `/redoc`.

**No test framework is configured yet.** Validation has been manual E2E via `httpx` scripts. Pytest setup is a known pending task — don't claim "tests pass" unless you've actually written and run them.

**No linter/formatter is configured.**

Local Postgres needs `pgcrypto` and `citext` extensions; both are created by migration 0001 and both ship with Supabase by default.

## Architectural invariants — violating any is a bug

### 1. Multi-tenancy is the spine
Every business table has `company_id` (FK to `companies`). **Every business query must filter `.where(... .company_id == user.company_id)`.** There is no automatic row-level filter — it's enforced per route. See `app/routers/projects.py` for the pattern. Cross-tenant access returns **404, never 403** (anti-enumeration).

### 2. Async everywhere
Stack is fully async (`AsyncSession` on asyncpg). Never introduce a sync DB call. The per-request session dependency is `app.deps.get_db` (async generator).

### 3. `DATABASE_URL` is auto-rewritten
`app/database.py:_to_asyncpg_url` accepts `postgresql://`, `postgres://`, or `postgresql+asyncpg://` and normalizes to the asyncpg form. Paste the Supabase URL as-is — don't pre-prefix with `+asyncpg` in `.env`.

### 4. Auth dependency chain (`app/deps.py`)
Compose via `Depends()`:
- `get_current_user` → JWT decode + DB lookup + `is_active` check (401 on any failure)
- `require_active_subscription` → above + `companies.subscription_active` (402 if off)
- `require_role(*roles)` → `get_current_user` + role membership (403). **Does NOT check subscription** — reserve for routes that must work while unpaid (future billing/checkout).
- `require_subscription_and_role(*roles)` → subscription (402) **then** role (403). **This is the default for business mutation routes** (projects, workers, RDO). Order matters: an unpaid company sees 402, not 403.

The middleware does **not** auto-scope queries by `company_id`. Routes must do that explicitly (rule 1). Project-access checks (admin=company, engineer/client=membership) live in `app/access.py` (`user_can_see_project`, `get_project_or_404`) — import from there, never from another router.

### 5. JWT discipline
`security.decode_token(token, expected_type=...)` REQUIRES `expected_type` (`"access"` or `"refresh"`). It refuses tokens whose `typ` claim doesn't match — defense against using a refresh where an access is expected. Never bypass.

### 6. Refresh tokens are stateful, opaque jti
Schema: `refresh_tokens.jti_hash = sha256(jti)`. Revoke by setting `revoked_at`. Rotation = revoke old + insert new (see `_issue_token_pair` and `/auth/refresh` in `app/routers/auth.py`).

### 7. Invites use opaque tokens, NOT JWT
`secrets.token_urlsafe(32)` (256 bits). Only `sha256(token)` lives in the DB.
- `APP_ENV=development`: `POST /auth/invites` response includes `token` + `accept_url` for testing without an inbox.
- `APP_ENV=production`: both are `null`. Email is the only delivery channel.

The gate is `is_dev = settings.APP_ENV == "development"` in `app/routers/invites.create_invite`.

### 8. Email service is provider-pluggable and fail-soft
`app/services/email.py` defines an `EmailProvider` Protocol with two impls: `ConsoleEmailProvider` (logs the email; default) and `ResendEmailProvider` (httpx POST to Resend; no new SDK). Selected by `EMAIL_PROVIDER` env.

**Email send failure does not abort invite creation.** Invite is already persisted; failure is `WARNING`-logged and the route returns `email_sent: false`. The caller decides what to do.

### 9. PII masking is implicit in logs
`app/logging_setup.py` installs a Loguru `patcher` that masks email, CPF, CNPJ, and JWT in every record **before any sink fires**. Always log via `loguru.logger` — never `print`/`sys.stderr.write`, or PII bypasses the patcher.

### 10. Migration gotchas
Alembic autogenerate does NOT capture extensions, triggers, PL/pgSQL functions, or some CHECK constraint changes. The `set_updated_at` trigger and `pgcrypto`/`citext` extensions in migration 0001 were written by hand with `op.execute(...)`. **Always read the generated migration file** and add `op.execute(...)` blocks for anything Alembic missed.

The `set_updated_at` trigger uses `clock_timestamp()`, not `NOW()` — inside a transaction, `NOW()` returns the txn start time, which makes `updated_at == created_at` when INSERT and UPDATE happen back-to-back.

### 11. `from __future__ import annotations` breaks FastAPI body introspection
Pydantic v2 + FastAPI evaluate request body annotations at decorator time. With `from __future__ import annotations` they become lazy strings that fail to resolve. **Do not add it to files in `app/routers/`.** It's fine in `app/models.py`, `app/security.py`, etc.

### 12. Anti-enumeration defaults
- Login: 401 with identical `credenciais inválidas` for wrong-password AND non-existent email. Timing equalized via a precomputed `DUMMY_HASH` (argon2 of a throwaway string at module load in `app/security.py`).
- Cross-tenant resource access: 404 with `não encontrado`, never 403. Same message as "actually doesn't exist". See `get_project_or_404` in `app/access.py`.

### 13. Workers are NOT users; attendance lives under the RDO
- `workers` = field roster (pedreiro, servente...). They **never authenticate** — no login, no `users` row, no role. Managed by admin/engineer. Company-scoped by `company_id`.
- `attendance` FKs `daily_report_id` (CASCADE — presence dies with the RDO) and `worker_id` (RESTRICT — a worker with history can't be hard-deleted; `DELETE /workers/{id}` returns 409 and directs to `is_active=false`).
- **RDO (`daily_reports`) is immutable**: no `updated_at`, no PATCH route. A mis-filed RDO is deleted (admin only) and re-created. Attendance, being operational, *can* be added/removed after creation via the nested `attendance` sub-routes.
- Filing an RDO requires project access (`get_project_or_404`), so an engineer must be a `project_members` row for that project — not just any engineer in the company.

## Permissioning model

| Role | Projects visible | Can do |
|---|---|---|
| `admin` | All in company (no `project_members` needed) | CRUD projects; manage members; invites; workers CRUD; delete RDOs |
| `engineer` | Only where in `project_members` | File RDOs + attendance on assigned projects; workers CRUD |
| `client` | Only where in `project_members` | Read-only (projects, RDOs); no workers, no RDO creation |

Admins are **never** added to `project_members`. `POST /projects/{id}/members` rejects self-assignment with 400. Workers roster is company-wide (not per-project) — any admin/engineer manages it.

## Repository

GitHub remote was renamed from `UNOPSICOBURNO_productbyricch` to `CONTROL_SAAS`. The old name redirects, but the canonical URL is `https://github.com/ricchTheSlash/CONTROL_SAAS`. If `git push` errors with rename guidance, update with `git remote set-url`.
