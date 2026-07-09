"""
Schemas Pydantic v2 do RDO (Relatório Diário de Obra) e presença (attendance).

O RDO é o artefato central do produto: uma linha por obra por dia.
Presença é um detalhe opcional embutido no RDO — quem estava no canteiro.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Weather = Literal["clear", "cloudy", "rain", "storm"]
AttendanceStatus = Literal["present", "absent", "half_day"]


# --- Attendance ---------------------------------------------------------------

class AttendanceItem(BaseModel):
    """Item de presença enviado na criação do RDO ou via rota dedicada."""

    worker_id: uuid.UUID
    status: AttendanceStatus = "present"
    hours_worked: Decimal | None = Field(default=None, ge=0, le=24)
    notes: str | None = Field(default=None, max_length=500)


class AttendanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    daily_report_id: uuid.UUID
    worker_id: uuid.UUID
    worker_name: str
    worker_role: str
    status: AttendanceStatus
    hours_worked: Decimal | None
    notes: str | None


# --- RDO ----------------------------------------------------------------------

class RDOCreate(BaseModel):
    report_date: date
    weather: Weather | None = None
    crew_count: int = Field(ge=0)
    activities: str = Field(min_length=1, max_length=10_000)
    photo_urls: list[str] = Field(default_factory=list)

    # Presença opcional embutida. Cada worker_id precisa pertencer à company.
    attendance: list[AttendanceItem] = Field(default_factory=list)


class RDOResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    engineer_id: uuid.UUID | None
    report_date: date
    weather: Weather | None
    crew_count: int
    activities: str
    photo_urls: list[str]
    created_at: datetime


class RDODetailResponse(RDOResponse):
    """RDO + lista de presença (usado no GET de um RDO específico)."""

    attendance: list[AttendanceResponse]
