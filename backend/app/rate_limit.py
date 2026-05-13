"""
Rate limiting com slowapi.

Por que rate limit em endpoints de auth:
  - `/auth/login`: defesa contra força bruta. 5 tentativas por minuto por IP
    é generoso para usuário legítimo e devastador para atacante.
  - `/auth/invites/.../accept`: defesa contra enumeração de tokens. Mesmo
    o token tendo 256 bits (inviável forçar), limitar evita abuso.

Armazenamento (storage):
  - slowapi padrão é IN-MEMORY: cada instância do servidor mantém seu próprio
    contador. Em produção com múltiplas réplicas atrás de um load balancer,
    o atacante pode multiplicar o limite pelo número de réplicas.
  - Solução pra escalar: storage Redis (`limits[redis]`). Configurável via
    .env quando for o caso. Documentado em SECURITY.md.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address


# Identifica o cliente pelo IP (X-Forwarded-For respeitado se trust proxy
# estiver ativo no servidor). Trocar por user_id em endpoints autenticados.
limiter = Limiter(key_func=get_remote_address)
