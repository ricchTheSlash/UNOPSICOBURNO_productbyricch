"""
Ponto de entrada do backend.

Esta fase deixa apenas:
  - `GET /health`: confirma que o servidor sobe corretamente.
  - Lifespan que abre o pool de conexões no startup e fecha no shutdown.

Rotas de negócio (auth, projetos, RDO, assinaturas) virão nas próximas fases.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: abre o pool de conexões com o Postgres.
    await pool.open()
    try:
        yield
    finally:
        # Shutdown: devolve as conexões educadamente.
        await pool.close()


app = FastAPI(title="CGH SaaS", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Endpoint usado por monitoramento e pela gente em desenvolvimento."""
    return {"status": "ok"}
