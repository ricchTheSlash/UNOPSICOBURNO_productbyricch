"""
Schemas Pydantic v2 do checkout de assinatura.
"""
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# UNDEFINED de propósito fora: a tabela subscriptions só aceita esses 3
# (CHECK constraint). O pagador escolhe um explicitamente no checkout.
BillingType = Literal["PIX", "BOLETO", "CREDIT_CARD"]


class CheckoutRequest(BaseModel):
    billing_type: BillingType
    # Só necessário se o admin ainda não tem CPF/CNPJ cadastrado (o Asaas exige).
    cpf_cnpj: str | None = Field(default=None, max_length=20)


class CheckoutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subscription_id: uuid.UUID          # id local (tabela subscriptions)
    asaas_subscription_id: str | None
    plan: str
    status: str                         # espelho do status do Asaas
    billing_type: BillingType
    value_cents: int
    next_due_date: date | None
    # Link do checkout hospedado pelo Asaas (pagador acessa e paga).
    payment_url: str | None = None
    bank_slip_url: str | None = None    # PDF do boleto (quando BOLETO)
    # Lembrete pro front: assinatura só fica ativa quando o webhook confirmar.
    subscription_active: bool


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    asaas_subscription_id: str | None
    plan: str
    value_cents: int
    billing_type: str
    status: str
    next_due_date: date | None
    created_at: datetime
    updated_at: datetime
