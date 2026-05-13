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
    Após criar um convite, devolvemos os metadados + status do envio de e-mail.

    O TOKEN CRU é incluído APENAS em desenvolvimento (`APP_ENV=development`):
    é prático pro admin copiar o link e testar sem precisar de inbox. Em
    produção (`APP_ENV=production`), o token sai do banco apenas como hash
    e do servidor apenas via e-mail — a resposta da rota não o expõe.
    """

    invite_id: uuid.UUID
    email: EmailStr
    role: Literal["engineer", "client"]
    expires_at: datetime
    email_sent: bool                  # se o provider devolveu sucesso
    accept_url: str | None = None     # presente em dev; ausente em prod
    token: str | None = None          # presente em dev; ausente em prod


class InviteAcceptRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    cpf_cnpj: str | None = Field(default=None, max_length=20)
