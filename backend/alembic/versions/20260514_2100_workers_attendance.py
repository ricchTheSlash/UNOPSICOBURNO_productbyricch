"""workers + attendance tables

Revision ID: 0004_workers_attendance
Revises: 0003_project_members
Create Date: 2026-05-14 21:00:00

Núcleo operacional:
  * workers      -> efetivo de campo (NÃO são users do sistema)
  * attendance   -> presença de um worker num RDO específico

Decisões:
  - attendance.daily_report_id CASCADE: presença é detalhe do RDO; some com ele.
  - attendance.worker_id RESTRICT: worker com histórico não pode ser apagado
    (a rota DELETE de worker oferece desativação nesse caso).
  - UNIQUE(daily_report_id, worker_id): um worker aparece uma vez por RDO.
  - Trigger set_updated_at aplicado só em workers (attendance é imutável, como
    o RDO — sem updated_at).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_workers_attendance"
down_revision: Union[str, None] = "0003_project_members"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- workers --------------------------------------------------------------
    op.create_table(
        "workers",
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
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("employment_type", sa.Text(), nullable=False),
        sa.Column("cpf", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("daily_rate_cents", sa.Integer()),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
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
            "employment_type IN ('clt', 'diarista')",
            name="ck_workers_employment_type",
        ),
        sa.CheckConstraint(
            "daily_rate_cents IS NULL OR daily_rate_cents >= 0",
            name="ck_workers_daily_rate",
        ),
    )
    op.create_index("ix_workers_company_id", "workers", ["company_id"])

    # --- attendance -----------------------------------------------------------
    op.create_table(
        "attendance",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "daily_report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("hours_worked", sa.Numeric(4, 1)),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "daily_report_id", "worker_id", name="uq_attendance_report_worker"
        ),
        sa.CheckConstraint(
            "status IN ('present', 'absent', 'half_day')",
            name="ck_attendance_status",
        ),
        sa.CheckConstraint(
            "hours_worked IS NULL OR (hours_worked >= 0 AND hours_worked <= 24)",
            name="ck_attendance_hours",
        ),
    )
    op.create_index("ix_attendance_daily_report_id", "attendance", ["daily_report_id"])
    op.create_index("ix_attendance_worker_id", "attendance", ["worker_id"])

    # --- trigger updated_at em workers ---------------------------------------
    # A função set_updated_at() já existe (migration 0001). Só ligamos o trigger.
    op.execute(
        """
        CREATE TRIGGER trg_workers_updated_at
            BEFORE UPDATE ON workers
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_workers_updated_at ON workers")

    op.drop_index("ix_attendance_worker_id", table_name="attendance")
    op.drop_index("ix_attendance_daily_report_id", table_name="attendance")
    op.drop_table("attendance")

    op.drop_index("ix_workers_company_id", table_name="workers")
    op.drop_table("workers")
