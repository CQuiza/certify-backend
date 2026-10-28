"""Registro de acciones administrativas y de impersonación."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import request_id_var
from app.models.security_audit import SecurityAudit
from app.models.user import User


async def record(
    db: AsyncSession,
    *,
    actor: User | None,
    action: str,
    target_tenant_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
) -> SecurityAudit:
    ip = None
    user_agent = None
    if request is not None:
        ip = request.headers.get("cf-connecting-ip") or (
            request.client.host if request.client else None
        )
        user_agent = request.headers.get("user-agent")

    row = SecurityAudit(
        actor_id=actor.id if actor else None,
        actor_role=actor.role if actor else None,
        target_tenant_id=target_tenant_id,
        target_type=target_type,
        target_id=target_id,
        action=action,
        before=before,
        after=after,
        ip=ip,
        user_agent=user_agent,
        request_id=request_id_var.get(),
    )
    db.add(row)
    await db.flush()
    return row
