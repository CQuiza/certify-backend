"""Pruebas de búsqueda de cursos (endpoint + filtro por título/descripción)."""

import pytest

from app.models.course import Course

_MATCH_TITLE = "Curso Busqueda Integral Python"
_OTHER_TITLE = "Curso Arquitectura de Software"


@pytest.mark.asyncio
async def test_courses_search_filters_by_title_contains(db, client, superuser_token):
    async with db.begin():
        db.add_all(
            [
                Course(title=_MATCH_TITLE, description="Con introducción", status="published"),
                Course(title=_OTHER_TITLE, description="Otro curso", status="published"),
            ]
        )

    resp = await client.get(
        "/api/v1/courses",
        headers={"Authorization": f"Bearer {superuser_token}"},
        params={"search": "busqueda", "limit": 100},
    )
    assert resp.status_code == 200, resp.text
    titles = [c["title"] for c in resp.json()]
    assert _MATCH_TITLE in titles
    assert _OTHER_TITLE not in titles


@pytest.mark.asyncio
async def test_courses_search_filters_by_description(db, client, superuser_token):
    async with db.begin():
        db.add_all(
            [
                Course(title="Curso Alpha", description="Especialización avanzada en redes", status="published"),
                Course(title="Curso Beta", description="Fundamentos generales", status="published"),
            ]
        )

    resp = await client.get(
        "/api/v1/courses",
        headers={"Authorization": f"Bearer {superuser_token}"},
        params={"search": "redes", "limit": 100},
    )
    assert resp.status_code == 200, resp.text
    titles = [c["title"] for c in resp.json()]
    assert "Curso Alpha" in titles
    assert "Curso Beta" not in titles


@pytest.mark.asyncio
async def test_courses_search_empty_results(db, client, superuser_token):
    resp = await client.get(
        "/api/v1/courses",
        headers={"Authorization": f"Bearer {superuser_token}"},
        params={"search": "texto que no existe 9999", "limit": 100},
    )
    assert resp.status_code == 200
    assert resp.json() == []