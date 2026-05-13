"""
Camada de acesso ao banco — bem fininha de propósito.

Usamos `psycopg` (driver moderno do Postgres em Python) com um POOL de conexões.

Por que um pool, e não abrir conexão por requisição?
  - Abrir/fechar conexão TCP+TLS com o Supabase custa centenas de ms.
  - Um pool mantém N conexões prontas e empresta a quem precisar.
  - Em FastAPI, o pool nasce no startup e morre no shutdown da aplicação.

Como usar (próximas fases):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
            row = await cur.fetchone()
"""
from contextlib import asynccontextmanager
from typing import AsyncIterator

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from app.config import settings


# Pool global. min_size=1 para sempre haver uma conexão "morna"; max_size=10
# é confortável para um MVP. Ajuste conforme tráfego real.
pool: AsyncConnectionPool = AsyncConnectionPool(
    conninfo=settings.DATABASE_URL,
    min_size=1,
    max_size=10,
    # open=False: não tenta conectar ao importar este módulo;
    # quem decide quando abrir é o lifespan do FastAPI (main.py).
    open=False,
)


@asynccontextmanager
async def get_conn() -> AsyncIterator[AsyncConnection]:
    """Empresta uma conexão do pool e devolve ao final do bloco `async with`."""
    async with pool.connection() as conn:
        yield conn
