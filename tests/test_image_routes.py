import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routes.image_routes as image_routes


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _AsyncClientStub:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, _url, json=None):
        if self._exc is not None:
            raise self._exc
        return self._response


class _Db:
    def add(self, _obj):
        return None

    def commit(self):
        return None

    def close(self):
        return None


def _endpoint():
    router = image_routes.setup_image_routes()
    for route in router.routes:
        if getattr(route, "path", "") == "/api/images/generate":
            return route.endpoint
    raise AssertionError("/api/images/generate route not found")


def test_image_generate_requires_prompt(monkeypatch):
    monkeypatch.setattr(image_routes, "get_setting", lambda key, default=None: True if key == "a1111_enabled" else default)
    monkeypatch.setattr(image_routes, "get_current_user", lambda request: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_endpoint()(_Request({"prompt": "   "})))

    assert exc.value.status_code == 400
    assert exc.value.detail == "prompt is required"


def test_image_generate_returns_503_when_a1111_disabled(monkeypatch):
    monkeypatch.setattr(image_routes, "get_setting", lambda key, default=None: False if key == "a1111_enabled" else default)
    monkeypatch.setattr(image_routes, "get_current_user", lambda request: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_endpoint()(_Request({"prompt": "cat"})))

    assert exc.value.status_code == 503
    assert "A1111 image generation is not enabled" in exc.value.detail


def test_image_generate_calls_privilege_gate_for_authenticated_user(monkeypatch, tmp_path):
    settings = {
        "a1111_enabled": True,
        "a1111_defaults": {},
        "a1111_api_base": "http://a1111:7860",
        "app_public_url": "",
    }
    called = {"privilege": 0}

    monkeypatch.setattr(image_routes, "get_setting", lambda key, default=None: settings.get(key, default))
    monkeypatch.setattr(image_routes, "get_current_user", lambda request: "alice")
    monkeypatch.setattr(image_routes, "require_privilege", lambda request, privilege: called.__setitem__("privilege", called["privilege"] + 1))
    monkeypatch.setattr(image_routes, "GENERATED_IMAGES_DIR", str(tmp_path))
    monkeypatch.setattr(image_routes, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(image_routes, "GalleryImage", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(
        image_routes.httpx,
        "AsyncClient",
        lambda **kwargs: _AsyncClientStub(
            response=_FakeResponse(
                200,
                {
                    "images": ["data:image/png;base64,aGVsbG8="],
                    "info": '{"seed": 42}',
                },
            )
        ),
    )

    response = asyncio.run(_endpoint()(_Request({"prompt": "cat"})))

    assert called["privilege"] == 1
    assert response["image_url"].startswith("/api/generated-image/")
    assert response["seed"] == 42


def test_image_generate_non_200_surfaces_a1111_detail(monkeypatch):
    settings = {
        "a1111_enabled": True,
        "a1111_defaults": {},
        "a1111_api_base": "http://a1111:7860",
    }
    monkeypatch.setattr(image_routes, "get_setting", lambda key, default=None: settings.get(key, default))
    monkeypatch.setattr(image_routes, "get_current_user", lambda request: None)
    monkeypatch.setattr(
        image_routes.httpx,
        "AsyncClient",
        lambda **kwargs: _AsyncClientStub(
            response=_FakeResponse(
                500,
                {"detail": "backend overloaded"},
                text="raw backend error",
            )
        ),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_endpoint()(_Request({"prompt": "cat"})))

    assert exc.value.status_code == 502
    assert "backend overloaded" in exc.value.detail


def test_image_generate_unexpected_errors_are_sanitized(monkeypatch):
    settings = {
        "a1111_enabled": True,
        "a1111_defaults": {},
        "a1111_api_base": "http://a1111:7860",
    }
    monkeypatch.setattr(image_routes, "get_setting", lambda key, default=None: settings.get(key, default))
    monkeypatch.setattr(image_routes, "get_current_user", lambda request: None)
    monkeypatch.setattr(
        image_routes.httpx,
        "AsyncClient",
        lambda **kwargs: _AsyncClientStub(response=_FakeResponse(200, {"images": ["not base64!!"]})),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_endpoint()(_Request({"prompt": "cat"})))

    assert exc.value.status_code == 500
    assert exc.value.detail == "Image generation failed"
