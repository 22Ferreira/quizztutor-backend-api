"""
Utilitário para extrair o IP real do cliente.
Funciona corretamente atrás de Nginx / Docker com X-Forwarded-For.
"""
from fastapi import Request


def get_real_ip(request: Request) -> str:
    """
    Retorna o IP real do cliente.
    Prioridade: X-Forwarded-For → X-Real-IP → request.client.host
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Lista de IPs: "client, proxy1, proxy2" — queremos o primeiro
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"
