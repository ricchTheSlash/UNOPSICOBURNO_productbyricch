"""
Configurações da aplicação.

Centralizamos a leitura do .env em UM lugar só (objeto `settings`).
Vantagens didáticas:
  - O resto do código importa `settings.ASAAS_API_KEY` em vez de
    espalhar `os.getenv(...)` por todos os módulos.
  - Pydantic valida tipos: se faltar `DATABASE_URL`, o servidor falha
    AO SUBIR (não em produção, no meio de uma requisição).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # URL completa do Postgres (Supabase fornece pronta no painel).
    DATABASE_URL: str

    # Credenciais do Asaas. Em desenvolvimento, use a chave do sandbox.
    ASAAS_API_KEY: str
    ASAAS_BASE_URL: str = "https://sandbox.asaas.com/api"

    # Útil para liberar/bloquear comportamentos por ambiente.
    APP_ENV: str = "development"

    # Diz ao pydantic-settings: leia o arquivo .env na raiz do backend.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


# Instanciado uma única vez no startup. Importe e use:
#   from app.config import settings
settings = Settings()
