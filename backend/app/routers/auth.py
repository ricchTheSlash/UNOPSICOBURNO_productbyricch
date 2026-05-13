"""
Endpoints de autenticação.

  POST /auth/register   - self-service: cria company + admin
  POST /auth/login      - troca senha por par access+refresh
  POST /auth/refresh    - troca refresh válido por novo par (rotação)
  POST /auth/logout     - revoga refresh atual

Considerações de segurança:

  - Login NÃO informa "user não existe" vs "senha errada": ambos viram
    401 genérico (`credenciais inválidas`). Evita enumeração de usuários.
  - Refresh é ROTACIONADO: a cada uso, o antigo é revogado e um novo é
    emitido. Detecção de reuso (sinal de roubo) virá em PR futura.
  - Rate limit em /login: 10 req/min/IP. Login legítimo raramente excede 2.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.config import settings
from app.deps import get_db, get_current_user
from app.models import Company, RefreshToken, User
from app.rate_limit import limiter
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserPublic,
)
from app.security import (
    DUMMY_HASH,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_user_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        company_id=user.company_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
    )


async def _issue_token_pair(db: AsyncSession, user: User) -> TokenResponse:
    """Emite par (access, refresh) e persiste o refresh pra suportar revogação."""
    access = create_access_token(
        user_id=user.id, company_id=user.company_id, role=user.role
    )

    jti = uuid.uuid4()
    refresh, expires_at = create_refresh_token(user_id=user.id, jti=jti)
    db.add(
        RefreshToken(
            user_id=user.id,
            jti_hash=hash_token(str(jti)),
            expires_at=expires_at,
        )
    )
    await db.commit()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.JWT_ACCESS_MINUTES * 60,
        user=_to_user_public(user),
    )


# --- POST /auth/register ------------------------------------------------------

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,  # exigido pelo decorator do slowapi
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Cria empresa nova com o primeiro user (admin). Retorna par de tokens
    já logado — fluxo natural de "criei conta, já estou dentro"."""

    company = Company(name=payload.company_name, cnpj=payload.cnpj)
    db.add(company)
    await db.flush()  # popula company.id sem commitar a transação ainda

    user = User(
        company_id=company.id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role="admin",
        phone=payload.phone,
        cpf_cnpj=payload.cpf_cnpj,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        # E-mail já cadastrado (UNIQUE constraint). Mensagem genérica
        # pra não confirmar "esse e-mail tem cadastro".
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="não foi possível concluir o cadastro",
        )

    logger.info(f"register: nova company {company.id} admin {user.email}")
    return await _issue_token_pair(db, user)


# --- POST /auth/login ---------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == payload.email))

    # Mensagem unificada pra falha: evita enumeração de e-mails.
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="credenciais inválidas",
    )

    if user is None or not user.is_active:
        # Mesmo se o user não existir, ainda assim verificamos uma senha
        # dummy pra equalizar o timing (defesa contra timing attack).
        verify_password(payload.password, DUMMY_HASH)
        raise invalid

    if not verify_password(payload.password, user.password_hash):
        raise invalid

    logger.info(f"login: {user.email}")
    return await _issue_token_pair(db, user)


# --- POST /auth/refresh -------------------------------------------------------

@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Rotaciona refresh: revoga o antigo e emite par novo."""

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="refresh inválido",
    )

    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError:
        raise invalid

    try:
        user_id = uuid.UUID(claims["sub"])
        jti = claims["jti"]
    except (KeyError, ValueError):
        raise invalid

    # Confere se o refresh ainda existe no banco e não foi revogado.
    rt = await db.scalar(
        select(RefreshToken).where(RefreshToken.jti_hash == hash_token(jti))
    )
    if rt is None or rt.revoked_at is not None:
        # Possível reuso de refresh antigo: futuro logging/alerta aqui.
        raise invalid
    if rt.expires_at < _now():
        raise invalid

    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        raise invalid

    # Revoga o refresh usado, emite par novo.
    rt.revoked_at = _now()
    await db.flush()
    return await _issue_token_pair(db, user)


# --- POST /auth/logout --------------------------------------------------------

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoga o refresh enviado. Idempotente: refresh já revogado/inválido = 204."""
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
        jti = claims.get("jti")
        if not jti:
            return
    except TokenError:
        return

    rt = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.jti_hash == hash_token(jti),
            RefreshToken.user_id == user.id,
        )
    )
    if rt is not None and rt.revoked_at is None:
        rt.revoked_at = _now()
        await db.commit()
        logger.info(f"logout: {user.email}")
