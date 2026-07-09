"""
CRUD do roster de workers (efetivo de campo).

Acesso:
  - Todas as rotas exigem assinatura ativa.
  - admin e engineer gerenciam o roster (criar/editar/desativar/deletar).
  - client NÃO acessa (é investidor, não gestor de campo) — 403.
  - Tenant isolation: toda query filtra por company_id.

Sobre DELETE:
  worker com histórico de attendance NÃO pode ser hard-deletado (FK RESTRICT).
  Nesse caso a rota devolve 409 e sugere desativar (PATCH is_active=false).
  Worker sem histórico é removido de fato.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.deps import get_db, require_subscription_and_role
from app.models import Worker, User
from app.schemas.workers import WorkerCreate, WorkerResponse, WorkerUpdate


router = APIRouter(prefix="/workers", tags=["workers"])


async def _get_worker_or_404(
    db: AsyncSession, company_id: uuid.UUID, worker_id: uuid.UUID
) -> Worker:
    worker = await db.scalar(select(Worker).where(Worker.id == worker_id))
    if worker is None or worker.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="worker não encontrado")
    return worker


@router.post("", response_model=WorkerResponse, status_code=status.HTTP_201_CREATED)
async def create_worker(
    payload: WorkerCreate,
    user: User = Depends(require_subscription_and_role("admin", "engineer")),
    db: AsyncSession = Depends(get_db),
) -> Worker:
    worker = Worker(
        company_id=user.company_id,
        full_name=payload.full_name,
        role=payload.role,
        employment_type=payload.employment_type,
        cpf=payload.cpf,
        phone=payload.phone,
        daily_rate_cents=payload.daily_rate_cents,
    )
    db.add(worker)
    await db.commit()
    await db.refresh(worker)
    logger.info(f"worker criado: {worker.id} ({payload.role}) por {user.email}")
    return worker


@router.get("", response_model=list[WorkerResponse])
async def list_workers(
    include_inactive: bool = False,
    user: User = Depends(require_subscription_and_role("admin", "engineer")),
    db: AsyncSession = Depends(get_db),
) -> list[Worker]:
    """Lista o roster da company. Por padrão só ativos; `?include_inactive=true`
    inclui os desativados."""
    stmt = select(Worker).where(Worker.company_id == user.company_id)
    if not include_inactive:
        stmt = stmt.where(Worker.is_active.is_(True))
    stmt = stmt.order_by(Worker.full_name)
    rows = await db.scalars(stmt)
    return list(rows.all())


@router.get("/{worker_id}", response_model=WorkerResponse)
async def get_worker(
    worker_id: uuid.UUID,
    user: User = Depends(require_subscription_and_role("admin", "engineer")),
    db: AsyncSession = Depends(get_db),
) -> Worker:
    return await _get_worker_or_404(db, user.company_id, worker_id)


@router.patch("/{worker_id}", response_model=WorkerResponse)
async def update_worker(
    worker_id: uuid.UUID,
    payload: WorkerUpdate,
    user: User = Depends(require_subscription_and_role("admin", "engineer")),
    db: AsyncSession = Depends(get_db),
) -> Worker:
    worker = await _get_worker_or_404(db, user.company_id, worker_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(worker, field, value)
    await db.commit()
    await db.refresh(worker)
    logger.info(f"worker {worker_id} atualizado por {user.email}")
    return worker


@router.delete("/{worker_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_worker(
    worker_id: uuid.UUID,
    user: User = Depends(require_subscription_and_role("admin", "engineer")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Hard delete. Se o worker tiver histórico de attendance, a FK RESTRICT
    bloqueia — devolvemos 409 sugerindo desativar (PATCH is_active=false).
    """
    worker = await _get_worker_or_404(db, user.company_id, worker_id)
    await db.delete(worker)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="worker tem histórico de presença; desative-o (PATCH is_active=false) em vez de deletar",
        )
    logger.info(f"worker {worker_id} deletado por {user.email}")
