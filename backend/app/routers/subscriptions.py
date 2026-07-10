"""
Checkout de assinatura via Asaas.

  POST /subscriptions/checkout  - admin cria a assinatura e recebe o link de pagamento
  GET  /subscriptions/current   - admin consulta a assinatura corrente da empresa

Ponto crucial de autorização:
  Estas rotas usam `require_role("admin")` — NÃO `require_active_subscription`.
  É o caso de uso que justifica manter `require_role` sem checagem de assinatura:
  a empresa está justamente pagando PARA ter assinatura; exigir assinatura
  ativa aqui seria um deadlock (402 pra poder pagar).

Fluxo do checkout:
  1. Se a empresa já está ativa → 409.
  2. Se já existe uma assinatura não-terminal → reusa (idempotente): devolve
     o mesmo link em vez de criar uma 2ª assinatura no Asaas.
  3. Garante que o admin tem `asaas_customer_id` (cria o cliente se preciso;
     o Asaas exige CPF/CNPJ).
  4. Cria a assinatura mensal no Asaas.
  5. Persiste a linha local em `subscriptions` (status espelha o Asaas).
  6. Busca a 1ª cobrança pra devolver `payment_url` (checkout hospedado).

  A flag `companies.subscription_active` NÃO é ligada aqui — só quando o
  webhook do Asaas confirmar o pagamento (PR #8). Checkout cria a INTENÇÃO
  de pagar; a confirmação é assíncrona.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.config import settings
from app.deps import get_db, require_role
from app.models import Company, Subscription, User
from app.schemas.subscriptions import (
    CheckoutRequest,
    CheckoutResponse,
    SubscriptionResponse,
)
from app.services import asaas


router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

# Status de assinatura (lado Asaas) que consideramos "ainda viva" — nesses
# casos reusamos em vez de criar outra. Os demais (INACTIVE/EXPIRED/CANCELED)
# são terminais: um novo checkout cria uma assinatura nova.
_TERMINAL_STATUSES = {"INACTIVE", "EXPIRED", "CANCELED", "CANCELLED"}


def _asaas_http_error(exc: asaas.AsaasError) -> HTTPException:
    """Traduz erro do Asaas: 400 (dado do cliente) repassa; resto vira 502."""
    if exc.status_code == 400:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Asaas recusou: {exc.detail}")
    logger.warning(f"Asaas erro {exc.status_code}: {exc.detail}")
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="falha ao comunicar com o provedor de pagamento",
    )


async def _payment_links(asaas_subscription_id: str) -> tuple[str | None, str | None]:
    """Best-effort: busca a 1ª cobrança e devolve (invoiceUrl, bankSlipUrl)."""
    try:
        payment = await asaas.get_subscription_first_payment(
            subscription_id=asaas_subscription_id
        )
    except asaas.AsaasError as exc:
        logger.warning(f"não obtive link de pagamento: {exc}")
        return None, None
    if payment is None:
        return None, None
    return payment.get("invoiceUrl"), payment.get("bankSlipUrl")


@router.post("/checkout", response_model=CheckoutResponse, status_code=status.HTTP_201_CREATED)
async def checkout(
    payload: CheckoutRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    company = await db.scalar(select(Company).where(Company.id == admin.company_id))
    if company is None:  # defensivo — não deveria acontecer
        raise HTTPException(status_code=404, detail="empresa não encontrada")
    if company.subscription_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="empresa já tem assinatura ativa")

    # (2) reaproveita assinatura não-terminal existente (idempotência).
    existing = await db.scalar(
        select(Subscription)
        .where(Subscription.company_id == company.id)
        .order_by(Subscription.created_at.desc())
    )
    if (
        existing is not None
        and existing.asaas_subscription_id is not None
        and existing.status.upper() not in _TERMINAL_STATUSES
    ):
        payment_url, bank_slip_url = await _payment_links(existing.asaas_subscription_id)
        return CheckoutResponse(
            subscription_id=existing.id,
            asaas_subscription_id=existing.asaas_subscription_id,
            plan=existing.plan,
            status=existing.status,
            billing_type=existing.billing_type,  # type: ignore[arg-type]
            value_cents=existing.value_cents,
            next_due_date=existing.next_due_date,
            payment_url=payment_url,
            bank_slip_url=bank_slip_url,
            subscription_active=company.subscription_active,
        )

    # (3) garante cliente no Asaas.
    cpf_cnpj = admin.cpf_cnpj or payload.cpf_cnpj
    if admin.asaas_customer_id is None:
        if not cpf_cnpj:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="informe CPF/CNPJ para gerar a cobrança",
            )
        try:
            customer = await asaas.create_customer(
                name=admin.full_name,
                cpf_cnpj=cpf_cnpj,
                email=admin.email,
                phone=admin.phone,
            )
        except asaas.AsaasError as exc:
            raise _asaas_http_error(exc)
        admin.asaas_customer_id = customer["id"]
        if admin.cpf_cnpj is None:
            admin.cpf_cnpj = cpf_cnpj
        await db.flush()

    # (4) cria a assinatura no Asaas.
    next_due = date.today() + timedelta(days=settings.SUBSCRIPTION_FIRST_DUE_DAYS)
    try:
        sub = await asaas.create_subscription(
            customer_id=admin.asaas_customer_id,
            billing_type=payload.billing_type,
            value_cents=settings.SUBSCRIPTION_VALUE_CENTS,
            next_due_date=next_due,
            description=f"Assinatura {settings.SUBSCRIPTION_PLAN_NAME} — CGH SaaS",
        )
    except asaas.AsaasError as exc:
        raise _asaas_http_error(exc)

    # (5) persiste local.
    subscription = Subscription(
        company_id=company.id,
        asaas_subscription_id=sub.get("id"),
        plan=settings.SUBSCRIPTION_PLAN_NAME,
        value_cents=settings.SUBSCRIPTION_VALUE_CENTS,
        billing_type=payload.billing_type,
        status=sub.get("status", "PENDING"),
        next_due_date=next_due,
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)

    logger.info(
        f"checkout: company={company.id} sub={subscription.asaas_subscription_id} "
        f"billing={payload.billing_type} por {admin.email}"
    )

    # (6) link de pagamento (best-effort).
    payment_url, bank_slip_url = (None, None)
    if subscription.asaas_subscription_id:
        payment_url, bank_slip_url = await _payment_links(subscription.asaas_subscription_id)

    return CheckoutResponse(
        subscription_id=subscription.id,
        asaas_subscription_id=subscription.asaas_subscription_id,
        plan=subscription.plan,
        status=subscription.status,
        billing_type=subscription.billing_type,  # type: ignore[arg-type]
        value_cents=subscription.value_cents,
        next_due_date=subscription.next_due_date,
        payment_url=payment_url,
        bank_slip_url=bank_slip_url,
        subscription_active=company.subscription_active,
    )


@router.get("/current", response_model=SubscriptionResponse)
async def current_subscription(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> Subscription:
    """Assinatura mais recente da empresa. 404 se nunca houve checkout."""
    sub = await db.scalar(
        select(Subscription)
        .where(Subscription.company_id == admin.company_id)
        .order_by(Subscription.created_at.desc())
    )
    if sub is None:
        raise HTTPException(status_code=404, detail="nenhuma assinatura encontrada")
    return sub
