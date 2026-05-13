"""
CRUD de obras de CGH + atribuição de members.

Regras de acesso (tenant isolation + role):
  - Toda rota requer assinatura ativa (require_active_subscription).
  - Toda query filtra por user.company_id — sem isso, IDOR.
  - admin: vê todos os projetos da company; pode criar/editar/deletar; gerencia members.
  - engineer/client: vê APENAS projetos onde é member; não cria/edita/deleta;
    não gerencia members.

Por que admin não precisa estar em project_members:
  Admin é o responsável pela empresa — enxergar tudo é o estado natural.
  Se um dia for necessário "esconder uma obra de outro admin", o modelo
  precisa ser revisto (provavelmente com flag `is_archived` ou semelhante).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.deps import get_db, require_active_subscription, require_role
from app.models import CGHProject, ProjectMember, User
from app.schemas.projects import (
    MemberAddRequest,
    MemberResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)


router = APIRouter(prefix="/projects", tags=["projects"])


# --- Helpers ------------------------------------------------------------------

async def _user_can_see_project(db: AsyncSession, user: User, project_id: uuid.UUID) -> bool:
    """True se o user pode VER esse projeto. Admin: company match. Outros: member."""
    project = await db.scalar(select(CGHProject).where(CGHProject.id == project_id))
    if project is None or project.company_id != user.company_id:
        return False
    if user.role == "admin":
        return True
    member = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
        )
    )
    return member is not None


async def _get_project_or_404(
    db: AsyncSession, user: User, project_id: uuid.UUID
) -> CGHProject:
    """Carrega o projeto com checagem de acesso. 404 se não existir OU usuário
    não tiver permissão — não distingue (anti-enumeração)."""
    project = await db.scalar(select(CGHProject).where(CGHProject.id == project_id))
    if project is None or project.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="projeto não encontrado")
    if user.role != "admin":
        member = await db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user.id,
            )
        )
        if member is None:
            raise HTTPException(status_code=404, detail="projeto não encontrado")
    return project


# --- CRUD projetos ------------------------------------------------------------

@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> CGHProject:
    """Admin cria projeto na company dele."""
    project = CGHProject(
        company_id=admin.company_id,
        name=payload.name,
        location=payload.location,
        installed_power_kw=payload.installed_power_kw,
        start_date=payload.start_date,
        expected_end_date=payload.expected_end_date,
        status=payload.status,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    logger.info(f"projeto criado: {project.id} por {admin.email}")
    return project


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    user: User = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db),
) -> list[CGHProject]:
    """Lista projetos visíveis ao user (tenant-scoped + role-scoped)."""
    if user.role == "admin":
        stmt = (
            select(CGHProject)
            .where(CGHProject.company_id == user.company_id)
            .order_by(CGHProject.created_at.desc())
        )
    else:
        # engineer/client: só onde é member
        stmt = (
            select(CGHProject)
            .join(ProjectMember, ProjectMember.project_id == CGHProject.id)
            .where(
                CGHProject.company_id == user.company_id,
                ProjectMember.user_id == user.id,
            )
            .order_by(CGHProject.created_at.desc())
        )
    rows = await db.scalars(stmt)
    return list(rows.all())


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db),
) -> CGHProject:
    return await _get_project_or_404(db, user, project_id)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> CGHProject:
    """Update parcial. Apenas admin pode editar; só dentro da própria company."""
    project = await db.scalar(select(CGHProject).where(CGHProject.id == project_id))
    if project is None or project.company_id != admin.company_id:
        raise HTTPException(status_code=404, detail="projeto não encontrado")

    # `model_dump(exclude_unset=True)`: só campos que o cliente realmente enviou.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    await db.commit()
    await db.refresh(project)
    logger.info(f"projeto {project_id} atualizado por {admin.email}")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Hard delete. CASCADE remove daily_reports e project_members."""
    project = await db.scalar(select(CGHProject).where(CGHProject.id == project_id))
    if project is None or project.company_id != admin.company_id:
        raise HTTPException(status_code=404, detail="projeto não encontrado")
    await db.delete(project)
    await db.commit()
    logger.info(f"projeto {project_id} deletado por {admin.email}")


# --- Members ------------------------------------------------------------------

@router.get("/{project_id}/members", response_model=list[MemberResponse])
async def list_members(
    project_id: uuid.UUID,
    user: User = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db),
) -> list[MemberResponse]:
    """Lista members do projeto (precisa poder VER o projeto)."""
    if not await _user_can_see_project(db, user, project_id):
        raise HTTPException(status_code=404, detail="projeto não encontrado")

    stmt = (
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.assigned_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        MemberResponse(
            id=m.id,
            project_id=m.project_id,
            user_id=u.id,
            user_email=u.email,
            user_full_name=u.full_name,
            user_role=u.role,  # type: ignore[arg-type]
            assigned_at=m.assigned_at,
        )
        for m, u in rows
    ]


@router.post(
    "/{project_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    project_id: uuid.UUID,
    payload: MemberAddRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    """Admin adiciona user ao projeto.
    Validações:
      - projeto pertence à company do admin
      - user existe + pertence à mesma company
      - user não é admin (admins veem tudo automaticamente; redundante)
      - dupla atribuição → 409
    """
    project = await db.scalar(select(CGHProject).where(CGHProject.id == project_id))
    if project is None or project.company_id != admin.company_id:
        raise HTTPException(status_code=404, detail="projeto não encontrado")

    target = await db.scalar(select(User).where(User.id == payload.user_id))
    if target is None or target.company_id != admin.company_id:
        raise HTTPException(status_code=404, detail="usuário não encontrado na sua empresa")
    if not target.is_active:
        raise HTTPException(status_code=400, detail="usuário inativo")
    if target.role == "admin":
        raise HTTPException(
            status_code=400, detail="admins já veem todos os projetos; não precisa atribuir"
        )

    member = ProjectMember(
        project_id=project_id,
        user_id=payload.user_id,
        assigned_by_user_id=admin.id,
    )
    db.add(member)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="usuário já é member deste projeto")

    await db.refresh(member)
    logger.info(f"member adicionado: project={project_id} user={target.email} by={admin.email}")
    return MemberResponse(
        id=member.id,
        project_id=member.project_id,
        user_id=target.id,
        user_email=target.email,
        user_full_name=target.full_name,
        user_role=target.role,  # type: ignore[arg-type]
        assigned_at=member.assigned_at,
    )


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Admin remove user do projeto. Idempotente: 204 mesmo se já não era member."""
    project = await db.scalar(select(CGHProject).where(CGHProject.id == project_id))
    if project is None or project.company_id != admin.company_id:
        raise HTTPException(status_code=404, detail="projeto não encontrado")

    member = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if member is not None:
        await db.delete(member)
        await db.commit()
        logger.info(f"member removido: project={project_id} user={user_id} by={admin.email}")
