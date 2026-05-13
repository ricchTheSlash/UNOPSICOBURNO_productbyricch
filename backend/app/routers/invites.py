"""
Convites: admin gera token pra engineer/client; destinatário aceita.

  POST /auth/invites               - admin gera convite (devolve token cru)
  POST /auth/invites/{token}/accept - destinatário cria a conta

Por que essa separação em vez de "admin cria user direto":
  - O admin não escolhe a senha do destinatário (LGPD: ele não deveria
    ter posse temporária da senha de outra pessoa).
  - O destinatário valida o e-mail (ele só conhece o token se recebeu o
    e-mail do convite).
  - Aceitação registra IP/UA do destinatário (futura auditoria).

Em PR #5b ainda devolvemos o token no response — o admin manda o link
manualmente. PR #5c pluga envio por e-mail (Resend/Postmark).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.config import settings
from app.deps import get_db, require_role
from app.models import Invite, User
from app.rate_limit import limiter
from app.routers.auth import _issue_token_pair
from app.schemas.auth import (
    InviteAcceptRequest,
    InviteCreateRequest,
    InviteCreateResponse,
    TokenResponse,
)
from app.security import generate_opaque_token, hash_password, hash_token


router = APIRouter(prefix="/auth/invites", tags=["invites"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- POST /auth/invites -------------------------------------------------------

@router.post("", response_model=InviteCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: InviteCreateRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> InviteCreateResponse:
    """
    Admin cria convite. O TOKEN CRU é devolvido UMA VEZ aqui — em PR #5c
    será enviado por e-mail ao destinatário e o response esconderá o token.

    Restrições:
    - Só admin pode (require_role).
    - Não permite convidar e-mail que já existe COMO USER (no sistema todo).
    - Não permite convite duplicado pendente pro mesmo e-mail+empresa.
    """

    # E-mail já tem conta? Recusa.
    existing_user = await db.scalar(select(User).where(User.email == payload.email))
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="e-mail já cadastrado no sistema",
        )

    # Já existe convite pendente (não-aceito, não-expirado) pra esse e-mail nesta empresa?
    pending = await db.scalar(
        select(Invite).where(
            Invite.email == payload.email,
            Invite.company_id == admin.company_id,
            Invite.accepted_at.is_(None),
            Invite.expires_at > _now(),
        )
    )
    if pending is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="já existe convite pendente para este e-mail",
        )

    token = generate_opaque_token()
    expires_at = _now() + timedelta(hours=settings.INVITE_EXPIRATION_HOURS)

    invite = Invite(
        company_id=admin.company_id,
        invited_by_user_id=admin.id,
        email=payload.email,
        role=payload.role,
        token_hash=hash_token(token),
        expires_at=expires_at,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    logger.info(
        f"invite criado: company={admin.company_id} by={admin.email} "
        f"to={payload.email} role={payload.role}"
    )

    return InviteCreateResponse(
        invite_id=invite.id,
        email=invite.email,
        role=invite.role,  # type: ignore[arg-type]
        token=token,  # cru — só aparece aqui
        expires_at=expires_at,
    )


# --- POST /auth/invites/{token}/accept ----------------------------------------

@router.post("/{token}/accept", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def accept_invite(
    request: Request,
    token: str,
    payload: InviteAcceptRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Destinatário aceita convite informando senha + dados. Devolve par de
    tokens (já logado).
    """
    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="convite inválido ou expirado"
    )

    invite = await db.scalar(
        select(Invite).where(Invite.token_hash == hash_token(token))
    )
    if invite is None or invite.accepted_at is not None or invite.expires_at < _now():
        raise invalid

    # Defesa em profundidade: e-mail já virou user entre convite e aceite?
    existing = await db.scalar(select(User).where(User.email == invite.email))
    if existing is not None:
        raise invalid

    user = User(
        company_id=invite.company_id,
        email=invite.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=invite.role,
        phone=payload.phone,
        cpf_cnpj=payload.cpf_cnpj,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise invalid

    invite.accepted_at = _now()
    await db.flush()

    logger.info(f"invite aceito: {invite.email} virou user {user.id}")
    return await _issue_token_pair(db, user)
