"""
Schemas Pydantic v2 do roster de workers (efetivo de campo).
"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EmploymentType = Literal["clt", "diarista"]


class WorkerCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    role: str = Field(min_length=2, max_length=100)  # função no canteiro
    employment_type: EmploymentType
    cpf: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=20)
    daily_rate_cents: int | None = Field(default=None, ge=0)


class WorkerUpdate(BaseModel):
    """Todos opcionais (PATCH)."""

    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    role: str | None = Field(default=None, min_length=2, max_length=100)
    employment_type: EmploymentType | None = None
    cpf: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=20)
    daily_rate_cents: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class WorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    full_name: str
    role: str
    employment_type: EmploymentType
    cpf: str | None
    phone: str | None
    daily_rate_cents: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
