"""
Ponto de entrada do backend.

Wiring:
  - Loguru com mascaramento de PII (setup_logging)
  - CORS (lista de origens vem do .env via settings)
  - Rate limit (slowapi)
  - Routers: auth + invites
  - Health check com SELECT 1 no banco

Próxima PR (#6) liga o router de projects.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from loguru import logger

from app.config import settings
from app.database import engine
from app.logging_setup import setup_logging
from app.rate_limit import limiter
from app.routers import auth as auth_router
from app.routers import invites as invites_router
from app.routers import projects as projects_router
from app.routers import reports as reports_router
from app.routers import subscriptions as subscriptions_router
from app.routers import workers as workers_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(f"CGH SaaS startup — env={settings.APP_ENV}")
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("CGH SaaS shutdown — engine descartado")


app = FastAPI(title="CGH SaaS", version="0.2.0", lifespan=lifespan)


# --- Rate limit ---------------------------------------------------------------
# Limiter precisa ficar no state pro decorator @limiter.limit funcionar.
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


# slowapi devolve 429 por padrão; o handler abaixo formata como JSON.
@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content={"detail": "muitas tentativas — aguarde um pouco"},
    )


# --- CORS ---------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Routers ------------------------------------------------------------------
app.include_router(auth_router.router)
app.include_router(invites_router.router)
app.include_router(projects_router.router)
app.include_router(workers_router.router)
app.include_router(reports_router.router)
app.include_router(subscriptions_router.router)


# --- Health check -------------------------------------------------------------
@app.get("/health")
async def health() -> dict[str, str]:
    """Tenta um SELECT 1 no banco; 503 se DB cair."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
