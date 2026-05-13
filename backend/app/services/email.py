"""
Serviço de envio de e-mail (provider-agnóstico).

Decisões:
  - 2 providers: `console` (loga) e `resend` (HTTP real).
  - Escolha por `EMAIL_PROVIDER` no .env. Default: console — dev funciona
    sem cadastro nem chave externa.
  - Templates inline (HTML + texto). Jinja2 só se a quantidade crescer.
  - Sem dependência externa nova: HTTP cru via httpx (que já temos).
  - Erros NÃO derrubam a rota: log de WARNING e a função retorna False.
    Isso faz com que /auth/invites devolva sucesso mesmo se o e-mail
    falhar — o admin tem o token cru como backup em dev mode.

Por que Resend e não SendGrid/Mailgun:
  - Free tier generoso (100/dia, 3k/mês) sem cartão de crédito.
  - API absurdamente simples (POST único).
  - Setup do domínio remetente em 3 cliques. Pra MVP é o sweet spot.
"""
from typing import Protocol

import httpx
from loguru import logger

from app.config import settings


class EmailProvider(Protocol):
    """Contrato que TODO provider deve cumprir."""

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
    ) -> bool:
        """Devolve True se enviou; False se falhou (já logou o erro)."""
        ...


# --- Console (dev) ------------------------------------------------------------

class ConsoleEmailProvider:
    """
    Não envia nada — só loga. Perfeito pra desenvolvimento: você vê o
    conteúdo do e-mail (incluindo o link do convite com token) direto no log.
    """

    async def send(
        self, *, to: str, subject: str, html: str, text: str  # noqa: ARG002 (html só pra match assinatura)
    ) -> bool:
        logger.info(
            "[email/console] to={to} subject={subject}\n--- TEXT ---\n{text}\n--- /TEXT ---",
            to=to,
            subject=subject,
            text=text,
        )
        return True


# --- Resend (produção) --------------------------------------------------------

class ResendEmailProvider:
    """Envia via API do Resend (https://resend.com/docs)."""

    _ENDPOINT = "https://api.resend.com/emails"

    def __init__(self, api_key: str, sender: str) -> None:
        if not api_key:
            raise ValueError("RESEND_API_KEY vazio — configure no .env ou use EMAIL_PROVIDER=console")
        self._api_key = api_key
        self._sender = sender

    async def send(self, *, to: str, subject: str, html: str, text: str) -> bool:
        payload = {
            "from": self._sender,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self._ENDPOINT, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning(f"[email/resend] falha de rede: {exc}")
            return False

        if response.status_code >= 400:
            logger.warning(
                f"[email/resend] status={response.status_code} body={response.text[:200]}"
            )
            return False

        logger.info(f"[email/resend] enviado para {to} (subject={subject})")
        return True


# --- Factory ------------------------------------------------------------------

def _build_provider() -> EmailProvider:
    """Escolhe o provider de acordo com EMAIL_PROVIDER do .env."""
    name = settings.EMAIL_PROVIDER.lower()
    if name == "console":
        return ConsoleEmailProvider()
    if name == "resend":
        return ResendEmailProvider(api_key=settings.RESEND_API_KEY, sender=settings.RESEND_FROM)
    raise ValueError(
        f"EMAIL_PROVIDER inválido: {settings.EMAIL_PROVIDER!r}. "
        f"Use 'console' ou 'resend'."
    )


# Instância única do processo. Construída lazy — se a config estiver errada,
# o erro só aparece quando alguém TENTA mandar e-mail (não no import).
_provider: EmailProvider | None = None


def get_email_provider() -> EmailProvider:
    global _provider
    if _provider is None:
        _provider = _build_provider()
    return _provider


# --- API de alto nível: envio do convite --------------------------------------

def _render_invite(
    *, accept_url: str, role: str, company_name: str, expires_hours: int
) -> tuple[str, str, str]:
    """Renderiza (subject, html, text) do convite. Inline pra evitar Jinja2."""
    role_pt = {"engineer": "engenheiro(a)", "client": "cliente"}.get(role, role)
    subject = f"Convite para {company_name} no CGH SaaS"

    text = f"""Olá!

Você foi convidado(a) para entrar em {company_name} como {role_pt} no CGH SaaS — a plataforma de gestão de obras de Centrais Geradoras Hidrelétricas.

Para criar sua senha e ativar a conta, acesse o link abaixo:

  {accept_url}

O link expira em {expires_hours} horas.

Se você não esperava este convite, ignore este e-mail.

— Equipe CGH SaaS
"""

    html = f"""<!doctype html>
<html lang="pt-br">
<body style="font-family: -apple-system, system-ui, sans-serif; max-width: 560px; margin: 24px auto; padding: 0 16px; color: #1f2937;">
  <h1 style="font-size: 22px; margin-bottom: 8px;">Você foi convidado(a)</h1>
  <p>Olá!</p>
  <p>Você foi convidado(a) para entrar em <strong>{company_name}</strong> como
     <strong>{role_pt}</strong> no <strong>CGH SaaS</strong> &mdash; a plataforma
     de gestão de obras de Centrais Geradoras Hidrelétricas.</p>
  <p style="margin: 24px 0;">
    <a href="{accept_url}"
       style="display: inline-block; padding: 12px 20px; background: #0ea5e9; color: white; text-decoration: none; border-radius: 6px; font-weight: 600;">
      Criar minha conta
    </a>
  </p>
  <p style="color: #6b7280; font-size: 13px;">O link expira em {expires_hours} horas. Se você não esperava este convite, ignore este e-mail.</p>
  <p style="color: #6b7280; font-size: 13px;">&mdash; Equipe CGH SaaS</p>
</body>
</html>"""

    return subject, html, text


async def send_invite_email(
    *,
    to: str,
    accept_url: str,
    role: str,
    company_name: str,
    expires_hours: int,
) -> bool:
    """API alto-nível usada pelo router. Renderiza + envia."""
    subject, html, text = _render_invite(
        accept_url=accept_url,
        role=role,
        company_name=company_name,
        expires_hours=expires_hours,
    )
    provider = get_email_provider()
    return await provider.send(to=to, subject=subject, html=html, text=text)
