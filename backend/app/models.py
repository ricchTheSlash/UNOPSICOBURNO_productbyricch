"""
Modelos SQLAlchemy 2.0 (estilo moderno: Mapped[] + mapped_column).

Multi-tenancy:
  Toda entidade de domínio referencia `companies.id`. A regra é:
  "uma requisição autenticada só enxerga dados onde
   row.company_id == request.user.company_id". O middleware de autorização
   (PR #5b) garante isso; o banco aplica integridade referencial.

Por que SQLAlchemy 2.0 async + asyncpg?
  - asyncpg é o driver Postgres mais rápido em Python (não bloqueia o event loop).
  - SQLAlchemy 2.0 dá tipagem estática (Mapped[T]) que o mypy/pyright entendem,
    pegando erro de coluna inexistente em tempo de IDE.
  - Alembic gera migrations automaticamente a partir desses modelos
    (autogenerate) — fim do SQL escrito à mão.

Por que mantemos CHECK constraints no banco (e não só em Pydantic)?
  Defesa em profundidade: mesmo que um bug deixe um valor inválido escapar
  da camada Python, o banco se recusa a aceitar. Nunca confie em uma única
  linha de defesa.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarativa única do projeto. Todos os modelos herdam daqui."""


# Tipo reutilizável para PK UUID com default gerado pelo Postgres (gen_random_uuid).
def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


# =============================================================================
# Company  -  tenant raiz. Tudo no sistema pertence a uma company.
# =============================================================================
class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    cnpj: Mapped[str | None] = mapped_column(Text, unique=True)

    # Middleware de "rotas protegidas" consulta esta flag em TODA request.
    # Mantemos em `companies` (não em users) porque a assinatura é da empresa:
    # 1 admin paga e todos os engineers/clients da empresa têm acesso.
    subscription_active: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    users: Mapped[list["User"]] = relationship(back_populates="company")
    projects: Mapped[list["CGHProject"]] = relationship(back_populates="company")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="company")


# =============================================================================
# User  -  quem opera o sistema. Sempre pertence a uma company.
# =============================================================================
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'engineer', 'client')",
            name="ck_users_role",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()

    # ON DELETE RESTRICT: não deletar empresa que ainda tem usuários.
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)

    # Soft-delete / suspensão. Middleware checa esta flag; usuários inativos
    # não conseguem logar nem usar refresh.
    is_active: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("true")
    )

    phone: Mapped[str | None] = mapped_column(Text)
    cpf_cnpj: Mapped[str | None] = mapped_column(Text)

    # Asaas trabalha com pessoas, não empresas — só o admin (billing contact)
    # tem um asaas_customer_id. Demais usuários ficam NULL.
    asaas_customer_id: Mapped[str | None] = mapped_column(Text, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    company: Mapped["Company"] = relationship(back_populates="users")


# =============================================================================
# CGHProject  -  uma obra de Central Geradora Hidrelétrica.
# =============================================================================
class CGHProject(Base):
    __tablename__ = "cgh_projects"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planning', 'in_progress', 'paused', 'completed')",
            name="ck_cgh_projects_status",
        ),
        CheckConstraint(
            "physical_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_physical_pct",
        ),
        CheckConstraint(
            "financial_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_financial_pct",
        ),
        CheckConstraint(
            "bunker_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_bunker_pct",
        ),
        CheckConstraint(
            "intake_canal_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_intake_pct",
        ),
        CheckConstraint(
            "powerhouse_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_powerhouse_pct",
        ),
        CheckConstraint(
            "turbine_assembly_progress_pct BETWEEN 0 AND 100",
            name="ck_cgh_projects_turbine_pct",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    installed_power_kw: Mapped[float | None] = mapped_column(Numeric(10, 2))
    start_date: Mapped[date | None] = mapped_column(Date)
    expected_end_date: Mapped[date | None] = mapped_column(Date)

    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'planning'")
    )

    physical_progress_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    financial_progress_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    bunker_progress_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    intake_canal_progress_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    powerhouse_progress_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    turbine_assembly_progress_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    company: Mapped["Company"] = relationship(back_populates="projects")
    reports: Mapped[list["DailyReport"]] = relationship(back_populates="project")
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


# =============================================================================
# ProjectMember  -  N:N entre users e cgh_projects.
# =============================================================================
# Quem participa de qual obra. O papel global do user (admin/engineer/client)
# já diz O QUE ele faz; este registro só estabelece A QUAIS projetos ele tem
# acesso. Admins enxergam tudo da sua company sem precisar de project_members.
class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("cgh_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Admin que atribuiu. SET NULL preserva histórico mesmo que o admin saia.
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    project: Mapped["CGHProject"] = relationship(back_populates="members")


# =============================================================================
# DailyReport  -  RDO. Uma linha por obra por dia.
# =============================================================================
class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (
        UniqueConstraint("project_id", "report_date", name="uq_daily_reports_project_date"),
        CheckConstraint(
            "weather IS NULL OR weather IN ('clear', 'cloudy', 'rain', 'storm')",
            name="ck_daily_reports_weather",
        ),
        CheckConstraint("crew_count >= 0", name="ck_daily_reports_crew_count"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("cgh_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Engenheiro que assinou o RDO. SET NULL preserva histórico se o user sair.
    engineer_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    weather: Mapped[str | None] = mapped_column(Text)
    crew_count: Mapped[int] = mapped_column(Integer, nullable=False)
    activities: Mapped[str] = mapped_column(Text, nullable=False)

    # Array de URLs do Supabase Storage. Sem updated_at de propósito:
    # um RDO assinado vira parte do histórico imutável.
    photo_urls: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    project: Mapped["CGHProject"] = relationship(back_populates="reports")


# =============================================================================
# Subscription  -  espelho local da assinatura no Asaas.
# =============================================================================
class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "billing_type IN ('PIX', 'BOLETO', 'CREDIT_CARD')",
            name="ck_subscriptions_billing_type",
        ),
        CheckConstraint("value_cents > 0", name="ck_subscriptions_value_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()

    # Assinatura pertence à empresa (não ao admin individual): se trocar o admin,
    # a empresa continua paga e ativa.
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ID da assinatura lá no Asaas. UNIQUE garante idempotência se o webhook
    # disparar 2x para o mesmo evento.
    asaas_subscription_id: Mapped[str | None] = mapped_column(Text, unique=True)

    plan: Mapped[str] = mapped_column(Text, nullable=False)
    value_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    billing_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'PENDING'")
    )
    next_due_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    company: Mapped["Company"] = relationship(back_populates="subscriptions")


# =============================================================================
# Invite  -  convite por e-mail para engineer/client entrar numa company.
# =============================================================================
# Modelo: o admin gera um convite com (email, role); o sistema devolve um
# token aleatório criptograficamente forte (32 bytes). Guardamos apenas o
# HASH do token (sha256) — se o banco vazar, o token cru não dá pra reverter.
# O destinatário acessa /auth/invites/{token}/accept com a senha que escolher.
class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint(
            "role IN ('engineer', 'client')",
            name="ck_invites_role",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Quem criou o convite (admin da company). SET NULL preserva o convite
    # mesmo que o admin saia da empresa.
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)

    # SHA-256 do token cru. Só o destinatário tem o token cru (foi enviado por
    # e-mail / copiado pelo admin no momento da geração).
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Marca de uso (idempotência): se já foi aceito, segunda tentativa falha.
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


# =============================================================================
# RefreshToken  -  rastreio de refresh tokens emitidos (permite revogação).
# =============================================================================
# JWT puro stateless seria mais simples, mas perde a capacidade de invalidar
# uma sessão (ex.: logout, "deslogar todos os dispositivos", admin
# suspendendo um user). Guardamos só o hash do JTI (ID único do token):
# se o banco vazar, ninguém consegue forjar refreshs.
#
# Política de rotação: a cada uso de refresh, o token antigo é marcado como
# revogado e um novo é emitido. Reuso de refresh antigo = sinal de roubo;
# tratamento (revogar toda a família) virá em PR futura se necessário.
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    jti_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
