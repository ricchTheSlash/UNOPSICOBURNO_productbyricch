"""
Ponto de entrada do backend.

Nesta fase (PR #5a) temos apenas:
  - `GET /health`: confirma que o servidor sobe e que o banco responde.
  - Lifespan que descarta o engine no shutdown (libera o pool do SQLAlchemy).

Rotas de negócio (auth, projetos, RDO, assinaturas) entram nas próximas PRs.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: SQLAlchemy abre conexões lazy na primeira query; nada a fazer aqui.
    try:
        yield
    finally:
        # Shutdown: devolve as conexões ao Postgres educadamente.
        await engine.dispose()


app = FastAPI(title="CGH SaaS", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """
    Health check executável: tenta um `SELECT 1` no banco.
    Se o Postgres estiver fora, retorna 503 (graças à exceção do engine).
    """
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
