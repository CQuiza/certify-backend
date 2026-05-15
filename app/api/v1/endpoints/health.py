"""Salud del servicio."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Estado del API")
async def health() -> dict[str, str]:
    return {"status": "ok"}
