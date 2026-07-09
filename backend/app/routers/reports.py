"""
RDO (Relatório Diário de Obra) + presença (attendance).

Aninhado sob /projects/{project_id}/reports.

Acesso:
  - Criar RDO / mexer em presença: admin OU engineer COM ACESSO à obra
    (admin: company match; engineer: membro do projeto). Client não cria.
  - Ler RDO: qualquer user com acesso à obra (inclui client).
  - Deletar RDO: admin (o RDO é imutável; deletar só corrige um mal-lançado).

Imutabilidade:
  daily_reports não tem updated_at — a narrativa do dia (atividades, clima,
  efetivo) é histórico. Não há PATCH de RDO. Presença, por ser dado
  operacional corrigível, PODE ser adicionada/removida após a criação.

1 RDO por obra por dia (UNIQUE project_id+report_date). Duplicata → 409.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.access import get_project_or_404, user_can_see_project
from app.deps import get_db, require_active_subscription, require_subscription_and_role
from app.models import Attendance, CGHProject, DailyReport, Worker, User
from app.schemas.reports import (
    AttendanceItem,
    AttendanceResponse,
    RDOCreate,
    RDODetailResponse,
    RDOResponse,
)


router = APIRouter(prefix="/projects/{project_id}/reports", tags=["reports"])


# --- Helpers ------------------------------------------------------------------

async def _get_report_or_404(
    db: AsyncSession, project: CGHProject, report_id: uuid.UUID
) -> DailyReport:
    """Carrega um RDO garantindo que pertence ao projeto informado."""
    report = await db.scalar(select(DailyReport).where(DailyReport.id == report_id))
    if report is None or report.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RDO não encontrado")
    return report


async def _validate_workers(
    db: AsyncSession, company_id: uuid.UUID, worker_ids: list[uuid.UUID]
) -> None:
    """
    Garante que todos os worker_ids existem e pertencem à company. Caso
    contrário, 400 (não distingue qual falhou — evita sondar ids de outra empresa).
    """
    if not worker_ids:
        return
    unique_ids = set(worker_ids)
    if len(unique_ids) != len(worker_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="worker repetido na lista de presença",
        )
    found = await db.scalars(
        select(Worker.id).where(
            Worker.id.in_(unique_ids), Worker.company_id == company_id
        )
    )
    if set(found.all()) != unique_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="lista de presença contém worker inexistente ou de outra empresa",
        )


async def _load_attendance(
    db: AsyncSession, report_id: uuid.UUID
) -> list[AttendanceResponse]:
    """Carrega presença de um RDO com nome/função do worker (evita N+1 no front)."""
    rows = (
        await db.execute(
            select(Attendance, Worker)
            .join(Worker, Worker.id == Attendance.worker_id)
            .where(Attendance.daily_report_id == report_id)
            .order_by(Worker.full_name)
        )
    ).all()
    return [
        AttendanceResponse(
            id=a.id,
            daily_report_id=a.daily_report_id,
            worker_id=a.worker_id,
            worker_name=w.full_name,
            worker_role=w.role,
            status=a.status,  # type: ignore[arg-type]
            hours_worked=a.hours_worked,
            notes=a.notes,
        )
        for a, w in rows
    ]


# --- RDO ----------------------------------------------------------------------

@router.post("", response_model=RDODetailResponse, status_code=status.HTTP_201_CREATED)
async def create_report(
    project_id: uuid.UUID,
    payload: RDOCreate,
    user: User = Depends(require_subscription_and_role("admin", "engineer")),
    db: AsyncSession = Depends(get_db),
) -> RDODetailResponse:
    # Acesso à obra (engineer precisa ser member; admin basta company).
    project = await get_project_or_404(db, user, project_id)

    await _validate_workers(
        db, user.company_id, [item.worker_id for item in payload.attendance]
    )

    report = DailyReport(
        project_id=project.id,
        engineer_id=user.id,
        report_date=payload.report_date,
        weather=payload.weather,
        crew_count=payload.crew_count,
        activities=payload.activities,
        photo_urls=payload.photo_urls,
    )
    db.add(report)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="já existe RDO para esta obra nesta data",
        )

    for item in payload.attendance:
        db.add(
            Attendance(
                daily_report_id=report.id,
                worker_id=item.worker_id,
                status=item.status,
                hours_worked=item.hours_worked,
                notes=item.notes,
            )
        )
    await db.commit()
    await db.refresh(report)

    logger.info(
        f"RDO criado: project={project_id} date={payload.report_date} "
        f"por {user.email} ({len(payload.attendance)} presenças)"
    )
    attendance = await _load_attendance(db, report.id)
    return RDODetailResponse(
        id=report.id,
        project_id=report.project_id,
        engineer_id=report.engineer_id,
        report_date=report.report_date,
        weather=report.weather,  # type: ignore[arg-type]
        crew_count=report.crew_count,
        activities=report.activities,
        photo_urls=report.photo_urls,
        created_at=report.created_at,
        attendance=attendance,
    )


@router.get("", response_model=list[RDOResponse])
async def list_reports(
    project_id: uuid.UUID,
    user: User = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db),
) -> list[DailyReport]:
    # get_project_or_404 permite admin/engineer-member/client-member.
    await get_project_or_404(db, user, project_id)
    rows = await db.scalars(
        select(DailyReport)
        .where(DailyReport.project_id == project_id)
        .order_by(DailyReport.report_date.desc())
    )
    return list(rows.all())


@router.get("/{report_id}", response_model=RDODetailResponse)
async def get_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    user: User = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db),
) -> RDODetailResponse:
    project = await get_project_or_404(db, user, project_id)
    report = await _get_report_or_404(db, project, report_id)
    attendance = await _load_attendance(db, report.id)
    return RDODetailResponse(
        id=report.id,
        project_id=report.project_id,
        engineer_id=report.engineer_id,
        report_date=report.report_date,
        weather=report.weather,  # type: ignore[arg-type]
        crew_count=report.crew_count,
        activities=report.activities,
        photo_urls=report.photo_urls,
        created_at=report.created_at,
        attendance=attendance,
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    user: User = Depends(require_subscription_and_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Só admin. CASCADE remove a presença junto."""
    project = await get_project_or_404(db, user, project_id)
    report = await _get_report_or_404(db, project, report_id)
    await db.delete(report)
    await db.commit()
    logger.info(f"RDO {report_id} deletado por {user.email}")


# --- Presença (attendance) ----------------------------------------------------

@router.post(
    "/{report_id}/attendance",
    response_model=AttendanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_attendance(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    payload: AttendanceItem,
    user: User = Depends(require_subscription_and_role("admin", "engineer")),
    db: AsyncSession = Depends(get_db),
) -> AttendanceResponse:
    """Adiciona a presença de um worker a um RDO já existente."""
    project = await get_project_or_404(db, user, project_id)
    report = await _get_report_or_404(db, project, report_id)
    await _validate_workers(db, user.company_id, [payload.worker_id])

    att = Attendance(
        daily_report_id=report.id,
        worker_id=payload.worker_id,
        status=payload.status,
        hours_worked=payload.hours_worked,
        notes=payload.notes,
    )
    db.add(att)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="este worker já tem presença registrada neste RDO",
        )

    worker = await db.scalar(select(Worker).where(Worker.id == payload.worker_id))
    logger.info(f"presença adicionada: report={report_id} worker={payload.worker_id}")
    return AttendanceResponse(
        id=att.id,
        daily_report_id=att.daily_report_id,
        worker_id=att.worker_id,
        worker_name=worker.full_name,
        worker_role=worker.role,
        status=att.status,  # type: ignore[arg-type]
        hours_worked=att.hours_worked,
        notes=att.notes,
    )


@router.delete(
    "/{report_id}/attendance/{worker_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_attendance(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    worker_id: uuid.UUID,
    user: User = Depends(require_subscription_and_role("admin", "engineer")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a presença de um worker num RDO. Idempotente."""
    project = await get_project_or_404(db, user, project_id)
    report = await _get_report_or_404(db, project, report_id)
    att = await db.scalar(
        select(Attendance).where(
            Attendance.daily_report_id == report.id,
            Attendance.worker_id == worker_id,
        )
    )
    if att is not None:
        await db.delete(att)
        await db.commit()
        logger.info(f"presença removida: report={report_id} worker={worker_id}")
