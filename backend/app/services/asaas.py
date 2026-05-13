"""
Serviço de integração com a API do Asaas.

Nesta fase implementamos APENAS `create_customer(...)`, suficiente para
cumprir o item 3 da Tarefa Inicial. Os próximos passos (criar assinatura,
processar webhook) entrarão em arquivos próximos a este, mantendo a
pasta `services/` como o lugar canônico de "fala-com-fora".

Sobre a API do Asaas:
  - Documentação: https://docs.asaas.com
  - A autenticação é por HEADER `access_token` (NÃO é Bearer JWT).
  - Em desenvolvimento, use o ambiente sandbox:
        ASAAS_BASE_URL=https://sandbox.asaas.com/api
    e a chave de sandbox da sua conta.

Por que `httpx.AsyncClient`?
  - FastAPI é async. Usar `requests` (síncrono) BLOQUEARIA o event loop
    durante a chamada HTTP — péssimo para throughput.
  - `httpx` tem API parecida com `requests`, mas suporta async nativamente.
"""
from typing import Optional, TypedDict

import httpx

from app.config import settings


# Endpoint de clientes na API v3 do Asaas.
_CUSTOMERS_PATH = "/v3/customers"


class AsaasCustomer(TypedDict, total=False):
    """
    Forma mínima do que o Asaas devolve ao criar um cliente.
    Anotamos só os campos que vamos efetivamente consumir.
    """
    id: str               # ex.: "cus_000005113026"  -> vai para users.asaas_customer_id
    name: str
    email: str
    cpfCnpj: str
    dateCreated: str


class AsaasError(Exception):
    """Erro de domínio para falhas vindas do Asaas."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Asaas API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


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

    headers = {
        # Particularidade do Asaas: header `access_token`, não `Authorization`.
        "access_token": settings.ASAAS_API_KEY,
        "Content-Type": "application/json",
        "User-Agent": "cgh-saas/0.1",
    }

    # AsyncClient com timeout: chamada pendurada NUNCA é solução.
    async with httpx.AsyncClient(base_url=settings.ASAAS_BASE_URL, timeout=15.0) as client:
        response = await client.post(_CUSTOMERS_PATH, json=payload, headers=headers)

    if response.status_code >= 400:
        # response.text é mais robusto que .json() — se o erro vier em HTML,
        # ainda conseguimos logar algo útil.
        raise AsaasError(response.status_code, response.text)

    # Em sucesso (200/201) o Asaas devolve JSON com o cliente criado.
    return response.json()
