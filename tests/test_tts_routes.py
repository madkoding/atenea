import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routes.tts_routes import setup_tts_routes


def _endpoint(router, method, path):
    method = method.upper()
    for route in router.routes:
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route.endpoint
    raise KeyError(f"Route {method} {path} not found")


def _service(**kwargs):
    defaults = {
        "available": True,
        "get_stats": lambda: {"ok": True},
        "synthesize_to_base64": lambda text: "Zm9v",
        "synthesize": lambda text: b"ID3\x04",
        "clear_cache": lambda: None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_synthesize_audio_mp3_returns_inline_mp3_headers():
    router = setup_tts_routes(_service(synthesize=lambda text: b"ID3\x03\x00\x00"))
    synth = _endpoint(router, "POST", "/api/tts/synthesize")

    response = asyncio.run(synth(SimpleNamespace(text="hello", format="audio")))

    assert response.media_type == "audio/mpeg"
    assert response.headers["content-disposition"] == "inline; filename=speech.mp3"


def test_synthesize_audio_wav_returns_inline_wav_headers():
    router = setup_tts_routes(_service(synthesize=lambda text: b"RIFF\x00\x00"))
    synth = _endpoint(router, "POST", "/api/tts/synthesize")

    response = asyncio.run(synth(SimpleNamespace(text="hello", format="audio")))

    assert response.media_type == "audio/wav"
    assert response.headers["content-disposition"] == "inline; filename=speech.wav"


def test_synthesize_unavailable_returns_503_message():
    router = setup_tts_routes(_service(available=False))
    synth = _endpoint(router, "POST", "/api/tts/synthesize")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(synth(SimpleNamespace(text="hello", format="audio")))

    assert exc.value.status_code == 503
    assert exc.value.detail == {"message": "TTS service not available"}


@pytest.mark.parametrize("fmt", ["audio", "base64"])
def test_synthesize_failure_response_is_consistent(fmt):
    if fmt == "audio":
        service = _service(synthesize=lambda text: None)
    else:
        service = _service(synthesize_to_base64=lambda text: None)
    router = setup_tts_routes(service)
    synth = _endpoint(router, "POST", "/api/tts/synthesize")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(synth(SimpleNamespace(text="hello", format=fmt)))

    assert exc.value.status_code == 500
    assert exc.value.detail == {"message": "Synthesis failed"}


def test_stats_failure_does_not_leak_internal_exception_message():
    def boom():
        raise RuntimeError("secret internals")

    router = setup_tts_routes(_service(get_stats=boom))
    stats = _endpoint(router, "GET", "/api/tts/stats")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(stats())

    assert exc.value.status_code == 500
    assert exc.value.detail == "Failed to get TTS stats"


def test_clear_cache_failure_does_not_leak_internal_exception_message():
    def boom():
        raise RuntimeError("cache path /tmp/private")

    router = setup_tts_routes(_service(clear_cache=boom))
    clear_cache = _endpoint(router, "POST", "/api/tts/clear-cache")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(clear_cache())

    assert exc.value.status_code == 500
    assert exc.value.detail == "Failed to clear TTS cache"
