"""Contexto de tenant y mixin de scoping.

El tenant activo se guarda en un ``ContextVar`` por request/tarea. La sesión
ORM aplica automáticamente ``with_loader_criteria`` sobre ``TenantScoped``,
de modo que toda consulta a tablas de negocio queda aislada por tenant sin
tocar cada repositorio.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

#: Valores especiales del ContextVar.
_UNSET = object()
_UNSCOPED = -1

_tenant_var: ContextVar[object] = ContextVar("tenant_id", default=_UNSET)


class TenantScoped:
    """Mixin declarativo: la tabla pertenece a un tenant.

    Agrega la columna ``tenant_id`` (FK a ``tenants.id``). Es la base sobre la
    que ``with_loader_criteria`` aplica el filtro automático.
    """

    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def is_tenant_context_set() -> bool:
    """True si el contexto ya fue resuelto (tenant o explícitamente unscoped)."""
    return _tenant_var.get() is not _UNSET


def current_tenant_id() -> int | None:
    """Tenant activo, o ``None`` si no aplica filtro (unscoped)."""
    value = _tenant_var.get()
    if value is _UNSET or value == _UNSCOPED:
        return None
    return int(value)  # type: ignore[arg-type]


def set_tenant_id(tenant_id: int) -> None:
    _tenant_var.set(int(tenant_id))


def reset_tenant_context(token) -> None:
    _tenant_var.reset(token)


def make_tenant_token(tenant_id: int | None):
    """Setea el contexto y devuelve el token para resetearlo."""
    return _tenant_var.set(_UNSCOPED if tenant_id is None else int(tenant_id))


@asynccontextmanager
async def tenant_ctx(tenant_id: int | None) -> AsyncIterator[None]:
    """Ejecuta un bloque con un tenant explícito (``None`` = unscoped)."""
    token = make_tenant_token(tenant_id)
    try:
        yield
    finally:
        _tenant_var.reset(token)


@asynccontextmanager
async def unscoped_ctx() -> AsyncIterator[None]:
    """Ejecuta un bloque sin filtro de tenant (operaciones globales)."""
    token = make_tenant_token(None)
    try:
        yield
    finally:
        _tenant_var.reset(token)


async def resolve_default_tenant_id(db) -> int:
    """Id del tenant por defecto (modo single / fallback)."""
    from sqlalchemy import select

    from app.core.settings import get_settings
    from app.models.tenant import Tenant

    settings = get_settings()
    result = await db.execute(
        select(Tenant.id).where(Tenant.slug == settings.default_tenant_slug)
    )
    tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        # Fallback: primer tenant activo.
        result = await db.execute(select(Tenant.id).order_by(Tenant.id).limit(1))
        tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        raise RuntimeError("No hay tenants configurados")
    return int(tenant_id)


async def ensure_current_tenant(db) -> int:
    """Garantiza un tenant activo en el contexto (por defecto si no se resolvió).

    Devuelve el tenant activo; ``-1`` para contexto explícitamente unscoped.
    """
    if is_tenant_context_set():
        cid = current_tenant_id()
        return -1 if cid is None else cid
    tenant_id = await resolve_default_tenant_id(db)
    set_tenant_id(tenant_id)
    return tenant_id