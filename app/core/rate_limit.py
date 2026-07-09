"""Limiter compartido para rate limiting."""

from slowapi import Limiter


def _rate_limit_key_func(request):
    forwarded = request.headers.get("X-Forwarded-For", "")
    ua = request.headers.get("User-Agent", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.client.host if request.client else "unknown"
    return f"{ip}|{ua}"


limiter = Limiter(key_func=_rate_limit_key_func)
