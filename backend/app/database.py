"""
Acesso ao Postgres via SQLAlchemy 2.0 async + asyncpg.

Por que SQLAlchemy 2.0 async em vez do psycopg cru:
  - ORM dá tipagem estática nos modelos (Mapped[T]); IDE pega `user.emial` antes
    de virar bug em produção.
  - Alembic gera migrations a partir dos modelos (autogenerate).
  - Mesmo padrão usado em fastapi/fullstack-fastapi-template, Sentry, e na
    maioria das stacks Python modernas — você aprende o que o mercado usa.

Por que asyncpg como driver:
  - É o driver Postgres mais rápido em Python (~30% mais rápido que psycopg
    em queries pesadas). Não bloqueia o event loop do FastAPI.

Sobre a "tradução" da DATABASE_URL:
  O Supabase entrega URLs no formato `postgresql://...` (padrão do psql).
  SQLAlchemy async exige `postgresql+asyncpg://...` para saber qual driver usar.
  Reescrevemos transparentemente para você não precisar lembrar disso no .env.
"""
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings


def _to_asyncpg_url(url: str) -> str:
    """
    Aceita `postgresql://` ou `postgres://` (formato do Supabase/Heroku) e
    devolve no formato que o SQLAlchemy async entende: `postgresql+asyncpg://`.
    Se a URL já estiver no formato `+asyncpg`, devolve como veio.
    """
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


# Engine único do processo. `pool_pre_ping=True` evita o clássico "server closed
# the connection unexpectedly" quando o Postgres reseta conexões ociosas.
engine: AsyncEngine = create_async_engine(
    _to_asyncpg_url(settings.DATABASE_URL),
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)

# Factory de sessões. `expire_on_commit=False` para que objetos retornados por
# rotas continuem utilizáveis depois do commit (padrão recomendado em FastAPI).
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """
    Dependency FastAPI: abre uma sessão por requisição e fecha ao final.

    Uso (próximas PRs):
        @app.get("/projects")
        async def list_projects(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with SessionLocal() as session:
        yield session
