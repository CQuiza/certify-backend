"""Configuración de logging y contexto de petición (request_id)."""

from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar

# Identificador de la petición actual (se propaga a los logs).
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Inyecta el ``request_id`` del contexto en cada registro de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | rid=%(request_id)s | %(message)s"
)


class JsonFormatter(logging.Formatter):
    """Emite registros en una línea JSON (ideal para Loki/agregadores)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "line": record.lineno,
            "request_id": getattr(record, "request_id", None) or "-",
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extra = getattr(record, "_log_extra", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO, log_format: str | None = None) -> None:
    """Configura el logging raíz.

    ``log_format``: ``"text"`` (default) o ``"json"``. Si es ``None`` se lee la
    variable de entorno ``LOG_FORMAT``.
    """
    fmt = (log_format or os.getenv("LOG_FORMAT", "text")).lower()
    handler = logging.StreamHandler()

    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)