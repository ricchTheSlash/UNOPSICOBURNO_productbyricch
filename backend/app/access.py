"""
Helpers de controle de acesso a projetos, compartilhados entre routers.

Regra única de visibilidade de projeto:
  - admin: vê qualquer projeto da PRÓPRIA company (não precisa de project_members)
  - engineer/client: vê apenas projetos onde consta em project_members

Cross-tenant e não-member colapsam no MESMO 404 (anti-enumeração): o caller
não consegue distinguir "não existe" de "existe mas não é seu".

Estes helpers NÃO são dependencies do FastAPI — são funções puras que recebem
a sessão + user já resolvidos e fazem as queries. Ficam aqui (e não no router
de projetos) pra que o router de RDO reuse sem importar função privada de
outro router.
"""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CGHProject, ProjectMember, User


async def user_can_see_project(
    db: AsyncSession, user: User, project_id: uuid.UUID
) -> bool:
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


async def get_project_or_404(
    db: AsyncSession, user: User, project_id: uuid.UUID
) -> CGHProject:
    """
    Carrega o projeto com checagem de acesso. 404 se não existir OU o usuário
    não tiver permissão — sem distinção (anti-enumeração).
    """
    project = await db.scalar(select(CGHProject).where(CGHProject.id == project_id))
    if project is None or project.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="projeto não encontrado")
    if user.role != "admin":
        member = await db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user.id,
            )
        )
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="projeto não encontrado"
            )
    return project
