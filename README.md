# CGH SaaS

SaaS para gestão de obras de **Centrais Geradoras Hidrelétricas (CGHs)**:
RDO (Relatório Diário de Obra), marcos técnicos (bunker, canal de adução,
casa de força, montagem de turbinas), dashboard de progresso físico/financeiro
e mensalidade recorrente via **Asaas**.

## Stack

| Camada      | Tecnologia                          |
|-------------|-------------------------------------|
| Backend     | Python + FastAPI                    |
| Banco       | Postgres (hospedado no Supabase)    |
| Pagamentos  | Asaas (PIX / Boleto / Cartão)       |
| Frontend    | React + Tailwind *(próxima fase)*   |
| Hospedagem  | VPS Linux na Hostinger *(próxima fase)* |

## Status atual

Esta entrega cobre **apenas a fundação** (Tarefa Inicial do produto):

1. ✅ Esquema SQL das 4 tabelas — `backend/migrations/001_init.sql`
2. ✅ Estrutura de pastas (boilerplate)
3. ✅ Serviço inicial de integração com Asaas — `create_customer()` em
       `backend/app/services/asaas.py`

Ainda **não** entram nesta fase: autenticação, rotas REST de negócio,
webhook do Asaas, frontend, deploy.

## Como rodar

Veja `backend/README.md`.

## Layout do repositório

```
.
├── backend/      # API em FastAPI (Python)
└── frontend/     # placeholder para React + Tailwind (próxima fase)
```
