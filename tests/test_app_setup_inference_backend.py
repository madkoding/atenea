import importlib.util
from pathlib import Path


def _load_setup_module():
    spec = importlib.util.spec_from_file_location("atenea_setup_inference_under_test", Path("app_setup.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_setup_local_inference_backend_returns_ok_when_backend_already_running(monkeypatch):
    setup = _load_setup_module()

    monkeypatch.setattr(
        setup,
        "detect_running_local_models",
        lambda: [{"backend": "ollama", "url": "http://localhost:11434", "models": "1"}],
    )

    assert setup.setup_local_inference_backend() is True


def test_setup_local_inference_backend_respects_skip_mode(monkeypatch):
    setup = _load_setup_module()

    monkeypatch.setenv("ATENEA_INFERENCE_SETUP", "skip")
    monkeypatch.setattr(setup, "detect_running_local_models", lambda: [])

    assert setup.setup_local_inference_backend() is True


def test_setup_local_inference_backend_uses_explicit_backend_choice(monkeypatch):
    setup = _load_setup_module()

    selected: list[str] = []
    monkeypatch.setattr(setup, "detect_running_local_models", lambda: [])
    monkeypatch.setenv("ATENEA_INFERENCE_SETUP", "auto")
    monkeypatch.setenv("ATENEA_INFERENCE_BACKEND", "hf-local")
    monkeypatch.setattr(
        setup,
        "_setup_selected_inference_backend",
        lambda choice: selected.append(choice) or True,
    )

    assert setup.setup_local_inference_backend() is True
    assert selected == ["hf-local"]


def test_setup_local_inference_backend_prompt_mode_uses_prompt_choice(monkeypatch):
    setup = _load_setup_module()

    selected: list[str] = []
    monkeypatch.setattr(setup, "detect_running_local_models", lambda: [])
    monkeypatch.setenv("ATENEA_INFERENCE_SETUP", "prompt")
    monkeypatch.delenv("ATENEA_INFERENCE_BACKEND", raising=False)
    monkeypatch.setattr(setup, "_can_prompt_inference_choice", lambda: True)
    monkeypatch.setattr(setup, "_prompt_inference_backend_choice", lambda: "ollama")
    monkeypatch.setattr(
        setup,
        "_setup_selected_inference_backend",
        lambda choice: selected.append(choice) or True,
    )

    assert setup.setup_local_inference_backend() is True
    assert selected == ["ollama"]


def test_setup_hf_local_reports_running_endpoint(monkeypatch):
    setup = _load_setup_module()

    class _Proc:
        returncode = 0

    monkeypatch.setattr(setup, "_pip_install", lambda *a, **k: _Proc())
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(
        setup,
        "_json_get",
        lambda url, timeout=2: {"data": [{"id": "local-model"}]} if url.endswith("/v1/models") else None,
    )

    assert setup._setup_hf_local() is True


def test_setup_ollama_local_accepts_existing_binary_outside_path(monkeypatch):
    setup = _load_setup_module()

    monkeypatch.setattr(setup.shutil, "which", lambda _name: None)
    monkeypatch.setattr(setup.os.path, "isfile", lambda p: p == "/usr/local/bin/ollama")
    monkeypatch.setattr(setup.os, "access", lambda p, _mode: p == "/usr/local/bin/ollama")

    assert setup._setup_ollama_local() is True


def test_setup_ollama_local_attempts_zstd_install_when_missing(monkeypatch):
    setup = _load_setup_module()

    monkeypatch.setattr(setup.os, "geteuid", lambda: 0)

    def _which(name: str):
        if name == "ollama":
            return None
        if name == "curl":
            return "/usr/bin/curl"
        if name == "zstd":
            return None
        if name == "apt-get":
            return "/usr/bin/apt-get"
        return None

    monkeypatch.setattr(setup.shutil, "which", _which)
    monkeypatch.setattr(setup.os.path, "isfile", lambda _p: False)
    monkeypatch.setattr(setup.os, "access", lambda _p, _mode: False)

    calls: list[list[str]] = []

    class _Proc:
        def __init__(self, returncode=0):
            self.returncode = returncode
            self.stderr = ""

    def _run(cmd, *args, **kwargs):
        if isinstance(cmd, list):
            calls.append(cmd)
            return _Proc(0)
        return _Proc(1)

    monkeypatch.setattr(setup.subprocess, "run", _run)
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(setup.sys.stdout, "isatty", lambda: False)

    ok = setup._setup_ollama_local()

    assert ok is False
    assert any(cmd[:3] == ["apt-get", "install", "-y"] and cmd[-1] == "zstd" for cmd in calls)


def test_setup_local_inference_backend_starts_ollama_api_when_not_running(monkeypatch):
    setup = _load_setup_module()

    calls = {"detect": 0}

    def _detect():
        calls["detect"] += 1
        return []

    monkeypatch.setattr(setup, "detect_running_local_models", _detect)
    monkeypatch.setenv("ATENEA_INFERENCE_SETUP", "auto")
    monkeypatch.setenv("ATENEA_INFERENCE_BACKEND", "ollama")
    monkeypatch.setattr(setup, "_setup_selected_inference_backend", lambda _choice: True)
    monkeypatch.setattr(setup, "_ensure_ollama_api_running", lambda: True)

    assert setup.setup_local_inference_backend() is True
    assert calls["detect"] >= 2


def test_setup_local_inference_backend_skips_ollama_autostart_for_other_backends(monkeypatch):
    setup = _load_setup_module()

    monkeypatch.setattr(setup, "detect_running_local_models", lambda: [])
    monkeypatch.setenv("ATENEA_INFERENCE_SETUP", "auto")
    monkeypatch.setenv("ATENEA_INFERENCE_BACKEND", "hf-local")
    monkeypatch.setattr(setup, "_setup_selected_inference_backend", lambda _choice: True)

    called = {"ollama_start": 0}

    def _mark_start():
        called["ollama_start"] += 1
        return True

    monkeypatch.setattr(setup, "_ensure_ollama_api_running", _mark_start)

    assert setup.setup_local_inference_backend() is True
    assert called["ollama_start"] == 0
