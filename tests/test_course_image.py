"""Imagen descriptiva de curso: subida, servido público, permisos y borrado."""

import io

import pytest
from PIL import Image

from app.api.v1.endpoints import courses as courses_endpoints


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class FakeMinio:
    """Doble en memoria del MinioClient (los tests no tienen MinIO)."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def ensure_bucket(self) -> None:
        pass

    def upload_bytes(self, object_name: str, data: bytes, *, content_type: str) -> None:
        self.store[object_name] = data

    def download_bytes(self, object_name: str) -> bytes:
        return self.store[object_name]

    def remove_object(self, object_name: str) -> None:
        self.store.pop(object_name, None)


@pytest.fixture
def fake_minio(monkeypatch):
    fake = FakeMinio()
    monkeypatch.setattr(
        courses_endpoints, "get_minio_client", lambda settings=None: fake
    )
    return fake


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), "red").save(buf, format="PNG")
    return buf.getvalue()


async def _create_course(client, token: str, title: str) -> dict:
    resp = await client.post(
        "/api/v1/courses", headers=hdr(token), json={"title": title}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_course_image_upload_serve_and_delete(client, superuser_token, fake_minio):
    course = await _create_course(client, superuser_token, "Curso con Imagen")
    cid = course["id"]
    assert course["has_image"] is False

    up = await client.post(
        f"/api/v1/courses/{cid}/image",
        headers=hdr(superuser_token),
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )
    assert up.status_code == 200, up.text
    assert up.json()["has_image"] is True

    # La imagen se sirve públicamente (catálogo), sin auth.
    img = await client.get(f"/api/v1/courses/{cid}/image")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/webp"

    # El listado expone has_image.
    listing = await client.get("/api/v1/courses", headers=hdr(superuser_token))
    row = next(c for c in listing.json() if c["id"] == cid)
    assert row["has_image"] is True

    # El catálogo público (CoursePublicRead) también expone has_image.
    await client.patch(
        f"/api/v1/courses/{cid}", headers=hdr(superuser_token), json={"status": "published"}
    )
    catalog = await client.get("/api/v1/courses?catalog=true")
    cat_row = next((c for c in catalog.json() if c["id"] == cid), None)
    assert cat_row is not None and cat_row["has_image"] is True

    # Borrado: limpia la imagen y el objeto.
    dele = await client.delete(
        f"/api/v1/courses/{cid}/image", headers=hdr(superuser_token)
    )
    assert dele.status_code == 200, dele.text
    assert fake_minio.store == {}
    gone = await client.get(f"/api/v1/courses/{cid}/image")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_course_image_requires_ownership(
    client, superuser_token, teacher_token, fake_minio
):
    course = await _create_course(client, superuser_token, "Curso Sin Docente")
    cid = course["id"]

    up = await client.post(
        f"/api/v1/courses/{cid}/image",
        headers=hdr(teacher_token),
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )
    assert up.status_code == 403


@pytest.mark.asyncio
async def test_course_image_rejects_non_image(client, superuser_token, fake_minio):
    course = await _create_course(client, superuser_token, "Curso No Imagen")
    cid = course["id"]

    up = await client.post(
        f"/api/v1/courses/{cid}/image",
        headers=hdr(superuser_token),
        files={"file": ("notes.txt", b"no soy una imagen", "text/plain")},
    )
    assert up.status_code == 400
