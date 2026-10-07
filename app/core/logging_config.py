"""Configuración de logging y contexto de petición (request_id)."""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
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


class LokiHandler(logging.Handler):
    """Envía registros a Loki por HTTP usando una cola + thread en background.

    Se activa si ``LOKI_URL`` está definida. Los registros se agrupan por
    (source, level) y se envían en lotes. Es fire-and-forget: nunca debe
    bloquear ni romper la app.
    """

    def __init__(
        self,
        url: str,
        *,
        source: str = "api",
        level: int = logging.INFO,
        batch_size: int = 50,
    ) -> None:
        super().__init__(level=level)
        base = url.rstrip("/")
        self.url = base if base.endswith("/loki/api/v1/push") else base + "/loki/api/v1/push"
        self.source = source
        self.batch_size = batch_size
        self._queue: "queue.Queue[logging.LogRecord | None]" = queue.Queue()

        import httpx

        self._client = httpx.Client(timeout=5.0)
        self._thread = threading.Thread(target=self._run, name="loki-shipper", daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put(record)
        except Exception:
            pass

    def _run(self) -> None:
        while True:
            try:
                first = self._queue.get(timeout=5.0)
            except queue.Empty:
                continue
            batch = [first]
            while not self._queue.empty() and len(batch) < self.batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            self._send(batch)

    def _send(self, batch: list[logging.LogRecord]) -> None:
        formatter = self.formatter or JsonFormatter()
        streams: dict[tuple[str, str], list[list[str]]] = {}
        for record in batch:
            key = (self.source, record.levelname.lower())
            line = formatter.format(record)
            ts_ns = int(record.created * 1_000_000_000)
            streams.setdefault(key, []).append([str(ts_ns), line])
        payload = {
            "streams": [
                {"stream": {"source": k[0], "level": k[1]}, "values": v}
                for k, v in streams.items()
            ]
        }
        try:
            self._client.post(self.url, json=payload)
        except Exception:
            pass


def configure_logging(level: int = logging.INFO, log_format: str | None = None) -> None:
    """Configura el logging raíz.

    ``log_format``: ``"text"`` (default) o ``"json"``. Si es ``None`` se lee la
    variable de entorno ``LOG_FORMAT``. Si ``LOKI_URL`` está definida, añade un
    ``LokiHandler`` (cola + thread) con source de ``LOG_SOURCE`` (default ``api``).
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

    # Evita el bucle de feedback: los requests de httpx/httpcore no deben
    # propagarse a root (se reenviarían a Loki de forma infinita).
    for _name in ("httpx", "httpcore"):
        _lg = logging.getLogger(_name)
        _lg.setLevel(logging.WARNING)
        _lg.propagate = False

    loki_url = os.getenv("LOKI_URL")
    if loki_url:
        try:
            loki = LokiHandler(loki_url, source=os.getenv("LOG_SOURCE", "api"))
            loki.setFormatter(JsonFormatter())
            loki.addFilter(RequestIdFilter())
            root.addHandler(loki)
        except Exception:
            logging.getLogger("logging_config").exception("No se pudo añadir el LokiHandler")

    root.setLevel(level)