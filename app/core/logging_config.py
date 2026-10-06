"""Configuración de logging y contexto de petición (request_id)."""

from __future__ import annotations

import logging
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


def configure_logging(level: int = logging.INFO) -> None:
    """Configura el logging raíz con el formato de la app y el request_id."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)