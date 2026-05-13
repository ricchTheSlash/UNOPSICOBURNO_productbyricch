"""
Schemas Pydantic v2 das rotas de auth + invites.

Distinção importante:
  - Schemas com "Request" no nome são INPUT (validados na entrada).
  - Schemas com "Response" são OUTPUT (serialização da saída).
  - Schemas internos (TokenPayload) auxiliam o código, não vão pra rede.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


# --- Register -----------------------------------------------------------------

class RegisterRequest(BaseModel):
    """Auto-cadastro do admin. Cria a `company` E o `user(role=admin)`."""

    # Empresa
    company_name: str = Field(min_length=2, max_length=200)
    cnpj: str | None = Field(default=None, max_length=20)

    # Usuário admin
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    cpf_cnpj: str | None = Field(default=None, max_length=20)


class UserPublic(BaseModel):
    """Forma do user retornada nas rotas (NUNCA inclui password_hash)."""

    id: uuid.UUID
    company_id: uuid.UUID
    email: EmailStr
    full_name: str
    role: Literal["admin", "engineer", "client"]
    is_active: bool


class TokenResponse(BaseModel):
    """Resposta padrão das rotas que emitem tokens (register/login/refresh)."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # segundos até o ACCESS expirar
    user: UserPublic


# --- Login --------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


# --- Refresh ------------------------------------------------------------------

class RefreshRequest(BaseModel):
    refresh_token: str


# --- Invites ------------------------------------------------------------------

class InviteCreateRequest(BaseModel):
    email: EmailStr
    role: Literal["engineer", "client"]


class InviteCreateResponse(BaseModel):
    """
    Após criar um convite, devolvemos o TOKEN CRU (única vez que ele aparece).
    Em PR #5c plugaremos envio por e-mail; até lá o admin copia/cola o link
    e envia manualmente.
    """

    invite_id: uuid.UUID
    email: EmailStr
    role: Literal["engineer", "client"]
    token: str          # cru — não fica no banco, só o hash
    expires_at: datetime


class InviteAcceptRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    cpf_cnpj: str | None = Field(default=None, max_length=20)
