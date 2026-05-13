"""
Alembic env.py — versão async.

Por que async aqui (e não o template síncrono padrão do Alembic):
  Nosso engine de aplicação já é async (asyncpg). Reaproveitar o mesmo formato
  de URL evita ter "DATABASE_URL pro app" e "DATABASE_URL pra migration" como
  duas configurações distintas — fonte clássica de bug ("rodou local, quebrou
  em prod porque a URL de migration estava desatualizada").
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.database import _to_asyncpg_url
from app.models import Base


config = context.config

# Injeta a URL vinda do .env (via pydantic-settings) na config do Alembic.
# Reescreve pra `postgresql+asyncpg://` se necessário.
config.set_main_option("sqlalchemy.url", _to_asyncpg_url(settings.DATABASE_URL))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata onde Alembic compara modelos vs estado do banco (`alembic check`,
# `alembic revision --autogenerate`).
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Modo offline: gera SQL bruto em vez de aplicar.
    Útil para revisar o que vai rodar antes de mexer em produção.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Modo online padrão: aplica direto no banco apontado por sqlalchemy.url."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
