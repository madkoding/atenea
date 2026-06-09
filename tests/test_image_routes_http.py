from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.image_routes as image_routes


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


def _client():
    app = FastAPI()
    app.include_router(image_routes.setup_image_routes())
    return TestClient(app)


def _patch_common(monkeypatch, settings, tmp_path):
    monkeypatch.setattr(image_routes, "get_setting", lambda key, default=None: settings.get(key, default))
    monkeypatch.setattr(image_routes, "get_current_user", lambda _request: None)
    monkeypatch.setattr(image_routes, "GENERATED_IMAGES_DIR", str(tmp_path))
    monkeypatch.setattr(image_routes, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(image_routes, "GalleryImage", lambda **kw: SimpleNamespace(**kw))


def test_image_generate_http_returns_503_when_disabled(monkeypatch, tmp_path):
    _patch_common(monkeypatch, {"a1111_enabled": False}, tmp_path)

    r = _client().post("/api/images/generate", json={"prompt": "cat"})

    assert r.status_code == 503
    assert "A1111 image generation is not enabled" in r.json()["detail"]


def test_image_generate_http_returns_502_with_a1111_error_detail(monkeypatch, tmp_path):
    settings = {"a1111_enabled": True, "a1111_defaults": {}, "a1111_api_base": "http://a1111:7860"}
    _patch_common(monkeypatch, settings, tmp_path)
    monkeypatch.setattr(
        image_routes.httpx,
        "AsyncClient",
        lambda **kwargs: _AsyncClientStub(response=_FakeResponse(500, {"detail": "backend overloaded"}, text="raw")),
    )

    r = _client().post("/api/images/generate", json={"prompt": "cat"})

    assert r.status_code == 502
    assert "backend overloaded" in r.json()["detail"]


def test_image_generate_http_timeout_maps_to_504(monkeypatch, tmp_path):
    settings = {"a1111_enabled": True, "a1111_defaults": {}, "a1111_api_base": "http://a1111:7860"}
    _patch_common(monkeypatch, settings, tmp_path)
    monkeypatch.setattr(
        image_routes.httpx,
        "AsyncClient",
        lambda **kwargs: _AsyncClientStub(exc=image_routes.httpx.TimeoutException("timeout")),
    )

    r = _client().post("/api/images/generate", json={"prompt": "cat"})

    assert r.status_code == 504


def test_image_generate_http_connect_error_maps_to_502(monkeypatch, tmp_path):
    settings = {"a1111_enabled": True, "a1111_defaults": {}, "a1111_api_base": "http://a1111:7860"}
    _patch_common(monkeypatch, settings, tmp_path)
    monkeypatch.setattr(
        image_routes.httpx,
        "AsyncClient",
        lambda **kwargs: _AsyncClientStub(exc=image_routes.httpx.ConnectError("connect")),
    )

    r = _client().post("/api/images/generate", json={"prompt": "cat"})

    assert r.status_code == 502
    assert "Cannot connect to A1111" in r.json()["detail"]


def test_image_generate_http_unexpected_error_is_sanitized(monkeypatch, tmp_path):
    settings = {"a1111_enabled": True, "a1111_defaults": {}, "a1111_api_base": "http://a1111:7860"}
    _patch_common(monkeypatch, settings, tmp_path)
    monkeypatch.setattr(
        image_routes.httpx,
        "AsyncClient",
        lambda **kwargs: _AsyncClientStub(response=_FakeResponse(200, {"images": ["not-base64!"]})),
    )

    r = _client().post("/api/images/generate", json={"prompt": "cat"})

    assert r.status_code == 500
    assert r.json() == {"detail": "Image generation failed"}


def test_image_generate_http_success_returns_payload(monkeypatch, tmp_path):
    settings = {
        "a1111_enabled": True,
        "a1111_defaults": {},
        "a1111_api_base": "http://a1111:7860",
        "app_public_url": "https://atenea.example.com",
    }
    _patch_common(monkeypatch, settings, tmp_path)
    monkeypatch.setattr(
        image_routes.httpx,
        "AsyncClient",
        lambda **kwargs: _AsyncClientStub(
            response=_FakeResponse(
                200,
                {
                    "images": ["data:image/png;base64,aGVsbG8="],
                    "info": '{"seed": 123}',
                },
            )
        ),
    )

    r = _client().post("/api/images/generate", json={"prompt": "cat", "width": 640, "height": 480})

    assert r.status_code == 200
    body = r.json()
    assert body["prompt"] == "cat"
    assert body["width"] == 640
    assert body["height"] == 480
    assert body["seed"] == 123
    assert body["image_url"].startswith("https://atenea.example.com/api/generated-image/")
