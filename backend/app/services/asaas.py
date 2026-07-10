"""
Serviço de integração com a API do Asaas.

Cobre o mínimo do ciclo de cobrança:
  - `create_customer(...)`      — cadastra a pessoa no Asaas
  - `create_subscription(...)`  — cria a assinatura mensal recorrente
  - `get_subscription_first_payment(...)` — busca a 1ª cobrança (link de pagamento)

O webhook que confirma pagamento (e liga `companies.subscription_active`)
entra na PR #8.

Sobre a API do Asaas:
  - Documentação: https://docs.asaas.com
  - A autenticação é por HEADER `access_token` (NÃO é Bearer JWT).
  - Valores monetários são em REAIS (float: 99.90), não centavos — convertemos.
  - Em desenvolvimento, use o ambiente sandbox:
        ASAAS_BASE_URL=https://sandbox.asaas.com/api
    e a chave de sandbox da sua conta.

Por que `httpx.AsyncClient`?
  - FastAPI é async. Usar `requests` (síncrono) BLOQUEARIA o event loop
    durante a chamada HTTP — péssimo para throughput.
  - `httpx` tem API parecida com `requests`, mas suporta async nativamente.

Mantemos todas as funções PURAS (sem acesso ao DB) — triviais de testar
com um mock HTTP. O caller (rota) é quem persiste no banco.
"""
from datetime import date
from typing import Optional, TypedDict

import httpx

from app.config import settings


_CUSTOMERS_PATH = "/v3/customers"
_SUBSCRIPTIONS_PATH = "/v3/subscriptions"


class AsaasCustomer(TypedDict, total=False):
    """Forma mínima do cliente devolvido pelo Asaas."""
    id: str               # ex.: "cus_000005113026"  -> vai para users.asaas_customer_id
    name: str
    email: str
    cpfCnpj: str
    dateCreated: str


class AsaasSubscription(TypedDict, total=False):
    """Forma mínima da assinatura devolvida pelo Asaas."""
    id: str               # ex.: "sub_000000123"  -> subscriptions.asaas_subscription_id
    status: str           # ACTIVE / INACTIVE / EXPIRED ...
    value: float
    nextDueDate: str
    billingType: str
    cycle: str


class AsaasPayment(TypedDict, total=False):
    """Forma mínima de uma cobrança (payment) devolvida pelo Asaas."""
    id: str
    status: str           # PENDING / RECEIVED / CONFIRMED / OVERDUE ...
    value: float
    invoiceUrl: str       # página de checkout hospedada pelo Asaas
    bankSlipUrl: str      # PDF do boleto (quando billingType=BOLETO)
    dueDate: str


class AsaasError(Exception):
    """Erro de domínio para falhas vindas do Asaas."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Asaas API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _headers() -> dict[str, str]:
    return {
        # Particularidade do Asaas: header `access_token`, não `Authorization`.
        "access_token": settings.ASAAS_API_KEY,
        "Content-Type": "application/json",
        "User-Agent": "cgh-saas/0.1",
    }


def _client() -> httpx.AsyncClient:
    # timeout explícito: chamada pendurada NUNCA é solução.
    return httpx.AsyncClient(base_url=settings.ASAAS_BASE_URL, timeout=15.0)


async def create_customer(
    *,
    name: str,
    cpf_cnpj: str,
    email: str,
    phone: Optional[str] = None,
    mobile_phone: Optional[str] = None,
) -> AsaasCustomer:
    """
    Cria um cliente no Asaas e retorna o objeto cru devolvido pela API.

    Use `*,` (keyword-only) para forçar chamadas como
        await create_customer(name="...", cpf_cnpj="...", email="...")
    Mais legível que uma chamada com 5 strings posicionais.

    O caller (futura rota de cadastro) é responsável por:
      1. Persistir `users` no banco.
      2. Chamar esta função.
      3. Gravar o `id` retornado em `users.asaas_customer_id`.

    Mantemos a função PURA (sem acesso ao DB) — assim ela é trivial de
    testar com `httpx.MockTransport` ou um stub.

    Tratamento de erros:
      - 400 -> dados inválidos (CPF/CNPJ malformado, e-mail repetido...).
      - 401 -> chave de API errada/expirada.
      - 429 -> rate limit; em produção, vale colocar retry com backoff.
      - 5xx -> instabilidade do Asaas; idem.
    """
    # Payload no formato esperado pelo Asaas (camelCase).
    payload: dict[str, str] = {
        "name": name,
        "cpfCnpj": cpf_cnpj,
        "email": email,
    }
    if phone is not None:
        payload["phone"] = phone
    if mobile_phone is not None:
        payload["mobilePhone"] = mobile_phone

    async with _client() as client:
        response = await client.post(_CUSTOMERS_PATH, json=payload, headers=_headers())

    if response.status_code >= 400:
        # response.text é mais robusto que .json() — se o erro vier em HTML,
        # ainda conseguimos logar algo útil.
        raise AsaasError(response.status_code, response.text)

    # Em sucesso (200/201) o Asaas devolve JSON com o cliente criado.
    return response.json()


async def create_subscription(
    *,
    customer_id: str,
    billing_type: str,
    value_cents: int,
    next_due_date: date,
    description: str,
    cycle: str = "MONTHLY",
) -> AsaasSubscription:
    """
    Cria uma assinatura recorrente no Asaas.

    - `value_cents` é convertido para reais (Asaas espera float).
    - `next_due_date` é a data da 1ª cobrança (formato ISO YYYY-MM-DD).
    - `billing_type`: 'PIX' | 'BOLETO' | 'CREDIT_CARD' | 'UNDEFINED'
      (UNDEFINED deixa o pagador escolher no checkout).
    - `cycle` MONTHLY para mensalidade.

    Devolve o objeto cru. O caller grava `id` em subscriptions.asaas_subscription_id.
    """
    payload: dict = {
        "customer": customer_id,
        "billingType": billing_type,
        "value": round(value_cents / 100, 2),
        "nextDueDate": next_due_date.isoformat(),
        "cycle": cycle,
        "description": description,
    }

    async with _client() as client:
        response = await client.post(_SUBSCRIPTIONS_PATH, json=payload, headers=_headers())

    if response.status_code >= 400:
        raise AsaasError(response.status_code, response.text)
    return response.json()


async def get_subscription_first_payment(
    *, subscription_id: str
) -> Optional[AsaasPayment]:
    """
    Busca a 1ª cobrança gerada pela assinatura, de onde sai o link de checkout
    (`invoiceUrl`) e o boleto (`bankSlipUrl`).

    Devolve None se ainda não houver cobranças geradas (o Asaas cria a 1ª
    logo após a assinatura, mas pode haver um pequeno delay).
    """
    async with _client() as client:
        response = await client.get(
            f"{_SUBSCRIPTIONS_PATH}/{subscription_id}/payments", headers=_headers()
        )

    if response.status_code >= 400:
        raise AsaasError(response.status_code, response.text)

    data = response.json().get("data", [])
    return data[0] if data else None
