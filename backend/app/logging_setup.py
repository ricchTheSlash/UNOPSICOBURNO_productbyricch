"""
Configuração do Loguru com mascaramento de PII.

Por que Loguru e não logging stdlib:
  - API muito mais simples (sem boilerplate de handlers/formatters).
  - Rotação de arquivo nativa (sem TimedRotatingFileHandler frágil).
  - Performance superior pra workloads async.

Por que mascarar PII:
  - LGPD: e-mails, CPFs e tokens em log de produção são vazamento esperando
    acontecer (rotação de logs para S3, backup pra fora do país, etc).
  - Defesa em profundidade: se um stack trace inclui um token JWT, o log
    NÃO deve guardar o token inteiro.

O mascaramento é feito ANTES do registro chegar a qualquer sink (console, arquivo).
"""
import re
import sys
from pathlib import Path

from loguru import logger

from app.config import settings


# Regexes intencionalmente conservadores: prefiro mascarar demais do que de menos.
_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_CPF_RE = re.compile(r"\b(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})\b")
_CNPJ_RE = re.compile(r"\b(\d{2})\.?(\d{3})\.?(\d{3})/?0001-?(\d{2})\b")
# JWT tem 3 partes em base64url separadas por '.'. Mascara o meio.
_JWT_RE = re.compile(r"\b(eyJ[A-Za-z0-9_-]{5,})\.([A-Za-z0-9_-]{5,})\.([A-Za-z0-9_-]{5,})\b")


def _mask_pii(message: str) -> str:
    """Aplica todos os mascaramentos em cadeia."""
    # e-mail: a***@gmail.com  (mantém domínio pra debug; oculta usuário)
    message = _EMAIL_RE.sub(lambda m: f"{m.group(1)[0]}***@{m.group(2)}", message)
    # CPF: ***.***.***-XX  (mantém apenas os 2 últimos dígitos)
    message = _CPF_RE.sub(r"***.***.***-\4", message)
    # CNPJ: **.***.***/0001-XX  (mantém apenas os 2 últimos dígitos)
    message = _CNPJ_RE.sub(r"**.***.***/0001-\4", message)
    # JWT: eyJxxx.***.<assinatura>  (mantém header pra debug do algorithm)
    message = _JWT_RE.sub(r"\1.***.***", message)
    return message


def _patcher(record: dict) -> None:
    """Hook que Loguru chama em cada record antes de formatar."""
    record["message"] = _mask_pii(record["message"])


def setup_logging() -> None:
    """
    Configura Loguru. Chamado UMA VEZ no startup do FastAPI.

    Em desenvolvimento: console com cores.
    Em qualquer ambiente: arquivo `logs/app.log` com rotação diária e
    retenção de 14 dias.
    """
    logger.remove()  # tira o handler padrão (stderr sem máscara)

    # Sink 1: console (stderr) — útil em dev e em containers (docker logs).
    logger.add(
        sys.stderr,
        level="DEBUG" if settings.APP_ENV == "development" else "INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        backtrace=True,
        diagnose=settings.APP_ENV == "development",  # NUNCA mostra valores de variáveis em prod
    )

    # Sink 2: arquivo com rotação diária. Diretório criado se não existir.
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logger.add(
        log_dir / "app.log",
        level="INFO",
        rotation="00:00",        # nova arquivo a cada meia-noite
        retention="14 days",     # apaga arquivos com mais de 14 dias
        compression="gz",        # comprime os antigos
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} - {message}"
        ),
        enqueue=True,            # gravação não bloqueia o event loop
    )

    # O patcher roda em cada mensagem, antes de qualquer sink ver.
    logger.configure(patcher=_patcher)
