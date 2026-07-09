"""
Schemas Pydantic v2 das rotas de projetos e members.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --- Projects -----------------------------------------------------------------

ProjectStatus = Literal["planning", "in_progress", "paused", "completed"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    location: str | None = Field(default=None, max_length=300)
    installed_power_kw: Decimal | None = Field(default=None, ge=0)
    start_date: date | None = None
    expected_end_date: date | None = None
    status: ProjectStatus = "planning"


class ProjectUpdate(BaseModel):
    """Tudo opcional: cliente envia só o que mudou (PATCH semantics)."""

    name: str | None = Field(default=None, min_length=2, max_length=200)
    location: str | None = Field(default=None, max_length=300)
    installed_power_kw: Decimal | None = Field(default=None, ge=0)
    start_date: date | None = None
    expected_end_date: date | None = None
    status: ProjectStatus | None = None

    physical_progress_pct: Decimal | None = Field(default=None, ge=0, le=100)
    financial_progress_pct: Decimal | None = Field(default=None, ge=0, le=100)
    bunker_progress_pct: Decimal | None = Field(default=None, ge=0, le=100)
    intake_canal_progress_pct: Decimal | None = Field(default=None, ge=0, le=100)
    powerhouse_progress_pct: Decimal | None = Field(default=None, ge=0, le=100)
    turbine_assembly_progress_pct: Decimal | None = Field(default=None, ge=0, le=100)


class ProjectResponse(BaseModel):
    """Forma do projeto retornada nas rotas."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    location: str | None
    installed_power_kw: Decimal | None
    start_date: date | None
    expected_end_date: date | None
    status: ProjectStatus

    physical_progress_pct: Decimal
    financial_progress_pct: Decimal
    bunker_progress_pct: Decimal
    intake_canal_progress_pct: Decimal
    powerhouse_progress_pct: Decimal
    turbine_assembly_progress_pct: Decimal

    created_at: datetime
    updated_at: datetime


# --- Project members ----------------------------------------------------------

class MemberAddRequest(BaseModel):
    user_id: uuid.UUID


class MemberResponse(BaseModel):
    """Member com dados básicos do user embedded (poupa N+1 no front)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID                       # id do registro project_members
    project_id: uuid.UUID
    user_id: uuid.UUID
    user_email: EmailStr
    user_full_name: str
    user_role: Literal["admin", "engineer", "client"]
    assigned_at: datetime
