from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.tts_routes import setup_tts_routes


class _Service:
    def __init__(self):
        self.available = True
        self._stats = {"ok": True}
        self._audio = b"ID3\x03\x00\x00"
        self._audio_b64 = "Zm9v"
        self._clear_error = None
        self._stats_error = None

    def get_stats(self):
        if self._stats_error is not None:
            raise self._stats_error
        return self._stats

    def synthesize(self, _text):
        return self._audio

    def synthesize_to_base64(self, _text):
        return self._audio_b64

    def clear_cache(self):
        if self._clear_error is not None:
            raise self._clear_error


def _client(service):
    app = FastAPI()
    app.include_router(setup_tts_routes(service))
    return TestClient(app)


def test_tts_stats_http_success():
    service = _Service()
    r = _client(service).get("/api/tts/stats")

    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_tts_stats_http_failure_is_sanitized():
    service = _Service()
    service._stats_error = RuntimeError("private details")
    r = _client(service).get("/api/tts/stats")

    assert r.status_code == 500
    assert r.json() == {"detail": "Failed to get TTS stats"}


def test_tts_synthesize_http_audio_response_headers():
    service = _Service()
    r = _client(service).post("/api/tts/synthesize", json={"text": "hello", "format": "audio"})

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert r.headers["content-disposition"] == "inline; filename=speech.mp3"


def test_tts_synthesize_http_base64_response():
    service = _Service()
    r = _client(service).post("/api/tts/synthesize", json={"text": "hello", "format": "base64"})

    assert r.status_code == 200
    assert r.json() == {"audio": "Zm9v"}


def test_tts_synthesize_http_unavailable_returns_503():
    service = _Service()
    service.available = False
    r = _client(service).post("/api/tts/synthesize", json={"text": "hello"})

    assert r.status_code == 503
    assert r.json() == {"detail": {"message": "TTS service not available"}}


def test_tts_clear_cache_http_failure_is_sanitized():
    service = _Service()
    service._clear_error = RuntimeError("/tmp/internal")
    r = _client(service).post("/api/tts/clear-cache")

    assert r.status_code == 500
    assert r.json() == {"detail": "Failed to clear TTS cache"}
