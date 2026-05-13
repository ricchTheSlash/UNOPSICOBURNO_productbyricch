# Security — CGH SaaS

Documento vivo. Atualizado a cada PR que toca segurança.

## Postura atual

| Domínio | Implementação atual | Notas |
|---|---|---|
| Hash de senha | `argon2id` (lib `argon2-cffi`, parâmetros PHC padrão) | OWASP recomendado |
| JWT | HS256, access 15min + refresh 7 dias | Segredo no `.env`, único por ambiente |
| Rotação de refresh | Sim — cada refresh emite novo par + revoga o antigo | Detecção de reuso fica em backlog |
| Storage de refresh | `refresh_tokens.jti_hash` (SHA-256 do JTI) | Permite revogação |
| Convites | Token opaco de 32 bytes (`secrets.token_urlsafe`), só o hash no banco | Expira em 48h, uso único |
| Rate limit | `slowapi` em memória — 5/min em `/register`, 10/min em `/login` e `/invites/.../accept` | Em prod com múltiplas réplicas, migrar pra Redis |
| CORS | Lista explícita via `CORS_ALLOW_ORIGINS` | NÃO usar `*` em produção |
| TLS | Responsabilidade do reverse proxy (Nginx + Let's Encrypt na VPS) | Não tratado a nível de app |
| Mascaramento em log | E-mail, CPF, CNPJ, JWT — masking via Loguru patcher | Antes de chegar em qualquer sink |
| CHECK constraints no banco | Role, status de projeto, billing_type, % de progresso | Defesa em profundidade |
| Tenant isolation | `company_id` em users/projects/subscriptions/invites + FK | Middleware da PR #6 vai forçar filtro |

## Checklist do pentest (a expandir)

### Auth
- [x] Senhas armazenadas como argon2id (NÃO em texto puro / NÃO em MD5 / NÃO em SHA-1)
- [x] Login com timing equalizado (verifica hash dummy quando user não existe)
- [x] Mensagem unificada de erro de login (não revela "user existe" vs "senha errada")
- [x] Refresh rotacionado a cada uso
- [x] Logout revoga refresh
- [x] Users inativos não conseguem logar nem refrescar
- [ ] Detecção de reuso de refresh revogado → revogar família inteira (backlog)
- [ ] CAPTCHA em `/login` após N falhas (backlog)

### Tokens
- [x] JWT com `typ` (access/refresh) para evitar troca de contexto
- [x] JTI dos refresh tokens armazenado como hash (vazamento de DB não dá acesso)
- [x] Convite armazenado como hash do token
- [x] Tokens de convite com 256 bits de entropia (`secrets.token_urlsafe(32)`)
- [ ] Algorithm pinning explícito no decode (atualmente lista única no settings — ok)

### Rede
- [x] CORS configurável, com lista explícita por ambiente
- [x] Rate limit em endpoints sensíveis (`/login`, `/register`, `/invites/.../accept`)
- [ ] HSTS + secure cookies (responsabilidade do reverse proxy)
- [ ] Cabeçalho `X-Frame-Options` (idem)
- [ ] Content-Security-Policy (configurado no front)

### Banco
- [x] Constraints CHECK validam role, status, % no banco
- [x] FKs com policies explícitas (RESTRICT/CASCADE/SET NULL conforme caso)
- [x] CITEXT para e-mail evita "Admin@x.com" e "admin@x.com" como contas distintas
- [ ] Row Level Security (RLS) do Supabase como camada extra (avaliar PR futura)

### Operacional
- [x] `.env` no `.gitignore` (segredo nunca commitado)
- [x] `.env.example` documenta as chaves sem valores reais
- [x] Loguru mascara PII (e-mail, CPF, CNPJ, JWT) antes de qualquer sink
- [ ] Rotação de `JWT_SECRET_KEY` sem invalidar todos os logins (precisa key ID)
- [ ] Backup de banco automatizado (responsabilidade do Supabase managed)

## Como reportar uma vulnerabilidade

Ainda em fase de MVP. Quando o produto estiver em produção, abrir
`security@<dominio>.com.br` e processo público de disclosure.

## Plano de evolução

Próximas iterações de segurança (não bloqueiam o MVP):

1. **Refresh reuse detection** — se um refresh já revogado for usado,
   revogar TODA a árvore de refresh do user e forçar relogin.
2. **MFA opcional** (TOTP, RFC 6238).
3. **Audit log dedicado** — tabela imutável `audit_events` com login,
   logout, convite emitido/aceito, mudança de role.
4. **Política de senha**: bloquear listas de "senhas mais comuns" (haveibeenpwned).
5. **HIBP K-Anonymity** no fluxo de cadastro (avisa se a senha já vazou).
