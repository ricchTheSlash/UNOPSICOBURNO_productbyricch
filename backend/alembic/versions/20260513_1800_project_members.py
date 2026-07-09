"""project_members table + drop cgh_projects.client_user_id

Revision ID: 0003_project_members
Revises: 0002_auth
Create Date: 2026-05-13 18:00:00

Substitui o atalho `cgh_projects.client_user_id` (que só permitia 1
cliente por obra) pela tabela N:N `project_members` (vários members
por obra; cada user pode estar em várias obras).

Decisões:
  - Sem coluna `role` em project_members: o papel global do user
    (admin/engineer/client) já diz O QUE ele é; o member só estabelece
    A QUAIS obras tem acesso.
  - Admins NÃO precisam de project_members: enxergam tudo da company.
  - UNIQUE(project_id, user_id) impede dupla atribuição.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_project_members"
down_revision: Union[str, None] = "0002_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- drop coluna antiga ---------------------------------------------------
    # Em produção real, com dados, faria isso em 2 passos: criar
    # project_members + popular a partir de client_user_id + drop coluna.
    # Em MVP pré-prod, drop direto.
    op.drop_column("cgh_projects", "client_user_id")

    # --- project_members ------------------------------------------------------
    op.create_table(
        "project_members",
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
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assigned_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "project_id", "user_id", name="uq_project_members_project_user"
        ),
    )
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_project_members_user_id", table_name="project_members")
    op.drop_index("ix_project_members_project_id", table_name="project_members")
    op.drop_table("project_members")

    op.add_column(
        "cgh_projects",
        sa.Column(
            "client_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
