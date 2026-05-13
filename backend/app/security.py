"""
Primitivas de segurança: hash de senha (argon2), JWT (PyJWT) e tokens
opacos de uso único (convite).

Por que **argon2id** em vez de bcrypt:
  - Argon2id venceu a competição PHC (Password Hashing Competition, 2015).
  - É resistente a ataque com GPU/ASIC (custa memória além de CPU).
  - É a recomendação atual da OWASP. bcrypt ainda é aceitável, mas argon2
    é o padrão moderno.

Por que **PyJWT** em vez de python-jose:
  - PyJWT é mantido pelo time do JWT.io, com manutenção ativa.
  - python-jose teve um histórico de CVEs (algorithm confusion) e ficou anos
    sem release. Mercado migrou.

Por que guardar refresh tokens no banco (em vez de stateless puro):
  - Permite revogar uma sessão específica (logout).
  - Permite revogar todas as sessões de um user (suspensão, troca de senha).
  - O custo é 1 SELECT extra por refresh — trade aceitável.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from app.config import settings


# argon2id com parâmetros padrão do PHC (time=2, memory=64MB, parallelism=8).
# Estes valores são considerados seguros e dão ~50ms de latência num servidor
# moderno — caro o suficiente para frear força bruta, rápido o suficiente
# para login interativo.
_hasher = PasswordHasher()

# Hash dummy real (não a senha real de ninguém) — usado em /auth/login quando
# o user não existe, para equalizar timing e atrapalhar enumeração via
# diferença de latência. Gerado UMA VEZ no load do módulo.
DUMMY_HASH: str = _hasher.hash("dummy-password-for-timing-equalization-only")


def hash_password(plain: str) -> str:
    """Devolve um hash argon2id pronto para gravar em users.password_hash."""
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    """
    True se `plain` bate com o hash; False caso contrário.
    Captura qualquer Argon2Error (mismatch, hash inválido, etc.) — facilita
    o uso em `if not verify_password(...)`.
    """
    try:
        return _hasher.verify(password_hash, plain)
    except Argon2Error:
        return False


# --- JWT ----------------------------------------------------------------------

TokenType = Literal["access", "refresh"]


def _now() -> datetime:
    """UTC consistente. Não usar datetime.utcnow (deprecated em 3.12)."""
    return datetime.now(timezone.utc)


def create_access_token(*, user_id: uuid.UUID, company_id: uuid.UUID, role: str) -> str:
    """
    Cria um JWT de acesso curto (15 min por padrão). Claims:
      - sub: user_id (subject, padrão JWT)
      - company_id, role: shortcut pra middleware não precisar dar SELECT
      - typ: 'access' (distingue de refresh)
      - iat, exp: timestamps padrão
    """
    now = _now()
    payload: dict = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": role,
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_ACCESS_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(*, user_id: uuid.UUID, jti: uuid.UUID) -> tuple[str, datetime]:
    """
    Cria um JWT de refresh (7 dias). `jti` é o ID único do token (vamos
    armazenar `sha256(jti)` em refresh_tokens pra permitir revogação).

    Devolve `(token_jwt, expires_at)` — o caller persiste a linha no banco
    com `expires_at` retornado, mantendo TTL alinhado.
    """
    now = _now()
    expires_at = now + timedelta(days=settings.JWT_REFRESH_DAYS)
    payload: dict = {
        "sub": str(user_id),
        "jti": str(jti),
        "typ": "refresh",
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


class TokenError(Exception):
    """Erro genérico de token inválido (expirado, assinatura ruim, tipo errado)."""


def decode_token(token: str, *, expected_type: TokenType) -> dict:
    """
    Valida assinatura + expiração + tipo. Lança TokenError em qualquer falha.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expirado") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token inválido") from exc

    if payload.get("typ") != expected_type:
        # Defesa contra "algorithm confusion": um refresh nunca pode ser usado
        # onde se espera um access (e vice-versa).
        raise TokenError(f"esperado token tipo {expected_type}, recebido {payload.get('typ')}")
    return payload


# --- Tokens opacos (convite e jti) --------------------------------------------

def generate_opaque_token(num_bytes: int = 32) -> str:
    """
    Token URL-safe criptograficamente forte (default: 32 bytes = 256 bits).
    Usado em convites: enviado por e-mail, nunca trafegado em headers, NÃO é JWT.
    """
    return secrets.token_urlsafe(num_bytes)


def hash_token(token: str) -> str:
    """
    SHA-256 hex. Usado pra armazenar `token_hash` em invites e `jti_hash`
    em refresh_tokens — se o banco vazar, o token cru não dá pra reverter.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
