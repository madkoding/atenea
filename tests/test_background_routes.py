import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routes.background_routes as background_routes


def _endpoint(router, method, path):
    method = method.upper()
    for route in router.routes:
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route.endpoint
    raise KeyError(f"Route {method} {path} not found")


class _Upload:
    def __init__(self, filename, content):
        self.filename = filename
        self._content = content

    async def read(self):
        return self._content


def _router(monkeypatch):
    import fastapi.dependencies.utils as dependency_utils

    monkeypatch.setattr(dependency_utils, "ensure_multipart_is_installed", lambda: None)
    return background_routes.setup_background_routes()


def test_upload_background_rejects_disallowed_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(background_routes, "BACKGROUNDS_DIR", str(tmp_path / "backgrounds"))
    upload = _endpoint(_router(monkeypatch), "POST", "/api/backgrounds/upload")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload(SimpleNamespace(), _Upload("evil.exe", b"x")))

    assert exc.value.status_code == 400
    assert "Only PNG" in exc.value.detail


def test_upload_background_renames_on_collision(tmp_path, monkeypatch):
    backgrounds = tmp_path / "backgrounds"
    backgrounds.mkdir(parents=True)
    (backgrounds / "wallpaper.png").write_bytes(b"old")
    monkeypatch.setattr(background_routes, "BACKGROUNDS_DIR", str(backgrounds))

    upload = _endpoint(_router(monkeypatch), "POST", "/api/backgrounds/upload")
    result = asyncio.run(upload(SimpleNamespace(), _Upload("wallpaper.png", b"new")))

    assert result["name"] == "wallpaper_1.png"
    assert (backgrounds / "wallpaper_1.png").read_bytes() == b"new"


def test_upload_background_rejects_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setattr(background_routes, "BACKGROUNDS_DIR", str(tmp_path / "backgrounds"))
    upload = _endpoint(_router(monkeypatch), "POST", "/api/backgrounds/upload")
    too_big = b"x" * (background_routes.MAX_FILE_SIZE + 1)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload(SimpleNamespace(), _Upload("a.png", too_big)))

    assert exc.value.status_code == 400
    assert "File too large" in exc.value.detail


def test_list_backgrounds_only_returns_allowed_files(tmp_path, monkeypatch):
    backgrounds = tmp_path / "backgrounds"
    backgrounds.mkdir(parents=True)
    (backgrounds / "a.png").write_bytes(b"png")
    (backgrounds / "b.jpg").write_bytes(b"jpg")
    (backgrounds / "note.txt").write_text("skip", encoding="utf-8")
    monkeypatch.setattr(background_routes, "BACKGROUNDS_DIR", str(backgrounds))

    list_backgrounds = _endpoint(_router(monkeypatch), "GET", "/api/backgrounds/list")
    result = asyncio.run(list_backgrounds())

    names = {item["name"] for item in result["backgrounds"]}
    assert names == {"a.png", "b.jpg"}


def test_serve_background_returns_404_for_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(background_routes, "BACKGROUNDS_DIR", str(tmp_path / "backgrounds"))
    serve = _endpoint(_router(monkeypatch), "GET", "/api/backgrounds/serve/{name}")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(serve("missing.png"))

    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "name",
    [
        "../escape.png",
        "..",
        "/tmp/x.png",
        "\\\\server\\share\\x.png",
        ".hidden.png",
        "trailingdot.png.",
        "trailingspace.png ",
        "bad\nname.png",
        "tab\tname.png",
    ],
)
def test_sanitize_filename_rejects_unsafe_names(name):
    with pytest.raises(HTTPException) as exc:
        background_routes._sanitize_filename(name)

    assert exc.value.status_code == 400


def test_sanitize_filename_accepts_safe_name():
    assert background_routes._sanitize_filename("Wallpaper-01 final.png") == "Wallpaper-01 final.png"
