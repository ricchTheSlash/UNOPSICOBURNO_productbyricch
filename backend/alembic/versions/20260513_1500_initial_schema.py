"""initial schema: companies, users, cgh_projects, daily_reports, subscriptions

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-13 15:00:00

Cria o esquema completo do MVP em UMA migration. Decisões importantes:

  * Multi-tenancy: tabela `companies` é a raiz. `users`, `cgh_projects` e
    `subscriptions` carregam `company_id` (FK). O filtro `company_id = ?` em
    toda query é o que isola tenants — middleware da PR #5b vai garantir isso.

  * `users.email` é GLOBALMENTE único (uma pessoa = uma conta). Convites por
    e-mail para uma empresa rejeitam endereço já existente.

  * `cgh_projects.client_user_id` é opcional; equipe completa do projeto
    (engineers + clients atribuídos) entra em `project_members` na PR #6.

  * `subscriptions.company_id` (não user_id): empresa assina, todos os
    membros usam. Trocar admin não derruba a assinatura.

  * Extensões `pgcrypto` (gen_random_uuid) e `citext` (e-mail case-insensitive)
    são criadas aqui. Supabase já tem ambas disponíveis.

  * Trigger `set_updated_at()` mantém updated_at sincronizado sem depender
    da aplicação se lembrar. `daily_reports` propositalmente NÃO tem
    updated_at — RDO assinado é histórico imutável.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Extensões ------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # --- companies ------------------------------------------------------------
    op.create_table(
        "companies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("cnpj", sa.Text(), unique=True),
        sa.Column(
            "subscription_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # --- users ----------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "email",
            postgresql.CITEXT(),
            nullable=False,
            unique=True,
        ),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text()),
        sa.Column("cpf_cnpj", sa.Text()),
        sa.Column("asaas_customer_id", sa.Text(), unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'engineer', 'client')",
            name="ck_users_role",
        ),
    )
    op.create_index("ix_users_company_id", "users", ["company_id"])

    # --- cgh_projects ---------------------------------------------------------
    op.create_table(
        "cgh_projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "client_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("location", sa.Text()),
        sa.Column("installed_power_kw", sa.Numeric(10, 2)),
        sa.Column("start_date", sa.Date()),
        sa.Column("expected_end_date", sa.Date()),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'planning'"),
        ),
        sa.Column(
            "physical_progress_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "financial_progress_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "bunker_progress_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "intake_canal_progress_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "powerhouse_progress_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "turbine_assembly_progress_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "status IN ('planning', 'in_progress', 'paused', 'completed')",
            name="ck_cgh_projects_status",
        ),
        sa.CheckConstraint(
            "physical_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_physical_pct",
        ),
        sa.CheckConstraint(
            "financial_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_financial_pct",
        ),
        sa.CheckConstraint(
            "bunker_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_bunker_pct",
        ),
        sa.CheckConstraint(
            "intake_canal_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_intake_pct",
        ),
        sa.CheckConstraint(
            "powerhouse_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_powerhouse_pct",
        ),
        sa.CheckConstraint(
            "turbine_assembly_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_turbine_pct",
        ),
    )
    op.create_index("ix_cgh_projects_company_id", "cgh_projects", ["company_id"])

    # --- daily_reports --------------------------------------------------------
    op.create_table(
        "daily_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cgh_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "engineer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("weather", sa.Text()),
        sa.Column("crew_count", sa.Integer(), nullable=False),
        sa.Column("activities", sa.Text(), nullable=False),
        sa.Column(
            "photo_urls",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "project_id", "report_date", name="uq_daily_reports_project_date"
        ),
        sa.CheckConstraint(
            "weather IS NULL OR weather IN ('clear', 'cloudy', 'rain', 'storm')",
            name="ck_daily_reports_weather",
        ),
        sa.CheckConstraint("crew_count >= 0", name="ck_daily_reports_crew_count"),
    )
    op.create_index("ix_daily_reports_project_id", "daily_reports", ["project_id"])
    op.create_index("ix_daily_reports_report_date", "daily_reports", ["report_date"])

    # --- subscriptions --------------------------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asaas_subscription_id", sa.Text(), unique=True),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("value_cents", sa.Integer(), nullable=False),
        sa.Column("billing_type", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("next_due_date", sa.Date()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "billing_type IN ('PIX', 'BOLETO', 'CREDIT_CARD')",
            name="ck_subscriptions_billing_type",
        ),
        sa.CheckConstraint("value_cents > 0", name="ck_subscriptions_value_positive"),
    )
    op.create_index("ix_subscriptions_company_id", "subscriptions", ["company_id"])

    # --- Trigger updated_at ---------------------------------------------------
    # Usamos `clock_timestamp()` em vez de `NOW()`: NOW() retorna o instante de
    # início da TRANSAÇÃO (idêntico para INSERTs e UPDATEs dentro do mesmo
    # bloco), enquanto clock_timestamp() devolve o relógio real do servidor.
    # Para `updated_at` queremos o relógio real — caso contrário um UPDATE
    # logo após um INSERT na mesma transação grava o mesmo timestamp.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for tbl in ("companies", "users", "cgh_projects", "subscriptions"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{tbl}_updated_at
                BEFORE UPDATE ON {tbl}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    # Inverte na ordem reversa pra respeitar as FKs.
    for tbl in ("companies", "users", "cgh_projects", "subscriptions"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl}")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")

    op.drop_index("ix_subscriptions_company_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_index("ix_daily_reports_report_date", table_name="daily_reports")
    op.drop_index("ix_daily_reports_project_id", table_name="daily_reports")
    op.drop_table("daily_reports")

    op.drop_index("ix_cgh_projects_company_id", table_name="cgh_projects")
    op.drop_table("cgh_projects")

    op.drop_index("ix_users_company_id", table_name="users")
    op.drop_table("users")

    op.drop_table("companies")

    # Extensões propositalmente NÃO são removidas: outras aplicações no mesmo
    # banco podem depender delas. Remoção manual fica a cargo do operador.
