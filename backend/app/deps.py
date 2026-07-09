"""
Dependencies do FastAPI para autenticação e autorização.

Hierarquia de proteção (composta com Depends):
  - `get_current_user`         -> JWT válido + user existe + is_active
  - `require_active_subscription` -> tudo acima + company.subscription_active
  - `require_role(...)`        -> tudo acima + role na lista permitida

Uso típico:

    @router.get("/projects")
    async def list_projects(
        user: User = Depends(require_active_subscription),
    ): ...

    @router.post("/invites")
    async def create_invite(
        admin: User = Depends(require_role("admin")),
    ): ...
"""
from __future__ import annotations

import uuid
from typing import AsyncIterator, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.models import User
from app.security import TokenError, decode_token


# `auto_error=True`: se faltar o header Authorization, FastAPI já devolve 403.
# Para 401 customizado, pegaríamos a exceção; o default é seguro o bastante.
_bearer = HTTPBearer(auto_error=True, scheme_name="JWT")


async def get_db() -> AsyncIterator[AsyncSession]:
    """Sessão por requisição. Idêntica ao get_db de database.py — mantida aqui
    pra facilitar import (`from app.deps import get_db`)."""
    async with SessionLocal() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Extrai o user do JWT. Falhas (token inválido, expirado, user inexistente,
    user inativo) viram 401.
    """
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sub inválido")

    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="usuário não existe")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="usuário inativo")
    return user


async def require_active_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Para rotas de negócio (CRUD de projetos, RDOs etc): exige que a EMPRESA
    do user esteja com assinatura ativa.
    """
    from app.models import Company  # import tardio: evita ciclo

    is_active = await db.scalar(
        select(Company.subscription_active).where(Company.id == user.company_id)
    )
    if not is_active:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="assinatura inativa — pague o boleto, pf",
        )
    return user


def require_role(*allowed: str) -> Callable[..., User]:
    """
    Factory: gera uma dependency que só deixa passar users com role em `allowed`.
    NÃO checa assinatura — use para rotas que devem funcionar mesmo sem
    assinatura ativa (ex.: futuras rotas de billing/checkout).

        Depends(require_role("admin"))
        Depends(require_role("admin", "engineer"))
    """

    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role requerida: {', '.join(allowed)}",
            )
        return user

    return _checker


def require_subscription_and_role(*allowed: str) -> Callable[..., User]:
    """
    Factory que exige AS DUAS coisas: assinatura ativa (402 se inativa) E role
    permitida (403 se não). É a dependency padrão de rotas de negócio que
    mutam dados (criar projeto, RDO, worker...).

    Ordem: assinatura primeiro (402), depois role (403). Assim uma empresa
    inadimplente vê "pague o boleto" em vez de "role errada".

        Depends(require_subscription_and_role("admin"))
        Depends(require_subscription_and_role("admin", "engineer"))
    """

    async def _checker(user: User = Depends(require_active_subscription)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role requerida: {', '.join(allowed)}",
            )
        return user

    return _checker
