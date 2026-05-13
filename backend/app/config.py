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
    # --- Banco ----------------------------------------------------------------
    # URL completa do Postgres (Supabase fornece pronta no painel).
    DATABASE_URL: str

    # --- Asaas ----------------------------------------------------------------
    ASAAS_API_KEY: str
    ASAAS_BASE_URL: str = "https://sandbox.asaas.com/api"

    # --- App ------------------------------------------------------------------
    APP_ENV: str = "development"

    # --- JWT ------------------------------------------------------------------
    # Segredo de assinatura dos JWTs. EM PRODUÇÃO use um valor longo (>= 32
    # bytes aleatórios) e único por ambiente. Nunca commitar.
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_MINUTES: int = 15          # access curto (limita estrago em roubo)
    JWT_REFRESH_DAYS: int = 7             # refresh longo (UX); rotaciona a cada uso

    # --- Convites -------------------------------------------------------------
    INVITE_EXPIRATION_HOURS: int = 48     # convite expira em 48h por padrão

    # --- CORS -----------------------------------------------------------------
    # Lista separada por vírgula. Em dev: "http://localhost:5173" (Vite).
    # Em prod: domínio do frontend.
    CORS_ALLOW_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]


settings = Settings()
