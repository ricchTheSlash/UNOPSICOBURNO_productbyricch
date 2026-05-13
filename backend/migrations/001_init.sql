-- =============================================================================
-- Migration 001 — Esquema inicial do SaaS de Gestão de Obras de CGHs
-- =============================================================================
-- Este arquivo cria as 4 tabelas centrais do MVP:
--   1) users           -> autenticação, papéis e flag de assinatura ativa
--   2) cgh_projects    -> as obras de Central Geradora Hidrelétrica
--   3) daily_reports   -> RDOs (Relatórios Diários de Obra)
--   4) subscriptions   -> assinaturas mensais geridas pelo Asaas
--
-- Como aplicar:
--   psql "$DATABASE_URL" -f backend/migrations/001_init.sql
--
-- Decisões importantes (para explicar ao professor):
--   - UUID em vez de SERIAL: evita "adivinhar" o próximo id e é seguro p/ APIs.
--   - CITEXT para e-mail: permite UNIQUE sem se preocupar com maiúscula/minúscula.
--   - CHECK constraints em colunas de "status" e "role": validam dados no
--     próprio banco, não dependendo só da aplicação (defesa em profundidade).
--   - subscription_active fica em `users` (e não em `subscriptions`) porque
--     middleware de autorização vai consultar essa flag em TODA requisição
--     protegida — manter em users evita um JOIN extra a cada chamada.
--   - Espelhamos o `status` do Asaas em `subscriptions.status` e atualizamos
--     a flag `users.subscription_active` quando o webhook chegar (próxima fase).
-- =============================================================================


-- Extensões necessárias --------------------------------------------------------
-- pgcrypto: fornece gen_random_uuid() para gerar UUIDs no próprio banco.
-- citext  : tipo "case-insensitive text" — perfeito para coluna de e-mail.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;


-- =============================================================================
-- TABELA: users
-- Quem usa o sistema. role determina o que cada um pode fazer.
-- =============================================================================
CREATE TABLE IF NOT EXISTS users (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    email               CITEXT       NOT NULL UNIQUE,
    -- hash da senha (bcrypt/argon2) — texto puro NUNCA é armazenado.
    password_hash       TEXT         NOT NULL,
    full_name           TEXT         NOT NULL,

    -- Papéis do MVP. Se um dia surgir um 4º papel, basta alterar este CHECK.
    role                TEXT         NOT NULL
                                     CHECK (role IN ('admin', 'engineer', 'client')),

    -- Flag consultada pelo middleware de rotas protegidas.
    -- Começa false; só vira true quando o webhook do Asaas confirmar pagamento.
    subscription_active BOOLEAN      NOT NULL DEFAULT FALSE,

    -- Dados pessoais que o Asaas exige ao cadastrar o cliente.
    phone               TEXT,
    cpf_cnpj            TEXT,

    -- ID do cliente correspondente lá no Asaas (preenchido após create_customer).
    asaas_customer_id   TEXT         UNIQUE,

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Índice já vem do UNIQUE em email, mas deixamos explícito o comentário:
-- buscas por e-mail (login) são o caminho mais quente da aplicação.


-- =============================================================================
-- TABELA: cgh_projects
-- Cada linha representa UMA obra de CGH pertencente a um cliente.
-- Os campos *_progress_pct alimentam o dashboard.
-- =============================================================================
CREATE TABLE IF NOT EXISTS cgh_projects (
    id                          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Cliente dono da obra. ON DELETE RESTRICT evita apagar um usuário
    -- que ainda tem obras vinculadas (proteção contra "perda silenciosa").
    client_id                   UUID         NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

    name                        TEXT         NOT NULL,
    location                    TEXT,
    installed_power_kw          NUMERIC(10,2),    -- potência instalada (kW)
    start_date                  DATE,
    expected_end_date           DATE,

    status                      TEXT         NOT NULL DEFAULT 'planning'
                                             CHECK (status IN (
                                                 'planning',     -- planejamento
                                                 'in_progress',  -- em execução
                                                 'paused',       -- parada
                                                 'completed'     -- concluída
                                             )),

    -- Progresso geral (alimenta cards do dashboard).
    -- NUMERIC(5,2) permite 0.00 até 100.00 com 2 casas decimais.
    physical_progress_pct       NUMERIC(5,2) NOT NULL DEFAULT 0
                                             CHECK (physical_progress_pct  BETWEEN 0 AND 100),
    financial_progress_pct      NUMERIC(5,2) NOT NULL DEFAULT 0
                                             CHECK (financial_progress_pct BETWEEN 0 AND 100),

    -- Marcos técnicos específicos de CGH (sugestão da especificação do produto):
    -- bunker (estrutura de concreto), canal de adução, casa de força e
    -- montagem de turbinas. Cada um tem seu % independente.
    bunker_progress_pct             NUMERIC(5,2) NOT NULL DEFAULT 0
                                                 CHECK (bunker_progress_pct           BETWEEN 0 AND 100),
    intake_canal_progress_pct       NUMERIC(5,2) NOT NULL DEFAULT 0
                                                 CHECK (intake_canal_progress_pct     BETWEEN 0 AND 100),
    powerhouse_progress_pct         NUMERIC(5,2) NOT NULL DEFAULT 0
                                                 CHECK (powerhouse_progress_pct       BETWEEN 0 AND 100),
    turbine_assembly_progress_pct   NUMERIC(5,2) NOT NULL DEFAULT 0
                                                 CHECK (turbine_assembly_progress_pct BETWEEN 0 AND 100),

    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Índice em client_id porque listar "obras do cliente X" é consulta frequente.
CREATE INDEX IF NOT EXISTS idx_cgh_projects_client_id ON cgh_projects(client_id);


-- =============================================================================
-- TABELA: daily_reports  (RDO — Relatório Diário de Obra)
-- Uma linha por dia por obra. O engenheiro de campo preenche.
-- =============================================================================
CREATE TABLE IF NOT EXISTS daily_reports (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Se a obra for deletada, os RDOs vão junto (não fazem sentido órfãos).
    project_id      UUID         NOT NULL REFERENCES cgh_projects(id) ON DELETE CASCADE,

    -- Quem assinou o RDO. SET NULL caso o engenheiro seja removido —
    -- preserva o histórico do relatório mesmo sem o autor.
    engineer_id     UUID                  REFERENCES users(id) ON DELETE SET NULL,

    report_date     DATE         NOT NULL,

    weather         TEXT         CHECK (weather IN ('clear', 'cloudy', 'rain', 'storm')),
    crew_count      INT          NOT NULL CHECK (crew_count >= 0),
    activities      TEXT         NOT NULL,

    -- Array de URLs das fotos (Supabase Storage ou outro upload entra depois).
    -- TEXT[] mantém simples nesta fase — sem tabela auxiliar de fotos.
    photo_urls      TEXT[]       NOT NULL DEFAULT ARRAY[]::TEXT[],

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- Regra de negócio: 1 RDO por obra por dia. Banco garante.
    UNIQUE (project_id, report_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_reports_project_id  ON daily_reports(project_id);
CREATE INDEX IF NOT EXISTS idx_daily_reports_report_date ON daily_reports(report_date);


-- =============================================================================
-- TABELA: subscriptions
-- Espelha as assinaturas que existem do lado do Asaas.
-- O webhook do Asaas (próxima fase) escreve/atualiza linhas aqui.
-- =============================================================================
CREATE TABLE IF NOT EXISTS subscriptions (
    id                      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id                 UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Identificador da assinatura lá no Asaas (ex.: "sub_000000123").
    -- UNIQUE para idempotência: se o mesmo webhook chegar 2x, não duplica.
    asaas_subscription_id   TEXT         UNIQUE,

    plan                    TEXT         NOT NULL,            -- ex.: 'monthly_basic'
    value_cents             INT          NOT NULL CHECK (value_cents > 0),

    billing_type            TEXT         NOT NULL
                                         CHECK (billing_type IN ('PIX', 'BOLETO', 'CREDIT_CARD')),

    -- Status idêntico ao que o Asaas devolve (ACTIVE, OVERDUE, CANCELED...).
    -- Mantemos como TEXT livre para não quebrar se o Asaas adicionar valores.
    status                  TEXT         NOT NULL DEFAULT 'PENDING',

    next_due_date           DATE,

    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);


-- =============================================================================
-- Trigger genérico para manter updated_at sincronizado.
-- =============================================================================
-- Função: sempre que um UPDATE acontecer numa tabela com updated_at,
-- substitui pelo NOW() automaticamente. Evita esquecer no código da aplicação.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_users_updated_at         ON users;
CREATE TRIGGER         trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_cgh_projects_updated_at  ON cgh_projects;
CREATE TRIGGER         trg_cgh_projects_updated_at
    BEFORE UPDATE ON cgh_projects
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_subscriptions_updated_at ON subscriptions;
CREATE TRIGGER         trg_subscriptions_updated_at
    BEFORE UPDATE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- daily_reports não tem updated_at porque um RDO, depois de assinado,
-- não deveria ser silenciosamente reescrito. Edições futuras criariam
-- um histórico (tabela à parte) em fase posterior.
