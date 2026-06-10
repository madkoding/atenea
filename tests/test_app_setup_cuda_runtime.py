import importlib.util
from pathlib import Path


def _load_setup_module():
    spec = importlib.util.spec_from_file_location("atenea_setup_cuda_under_test", Path("app_setup.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_llama_server_supports_gpu_backend_parses_help(monkeypatch):
    setup = _load_setup_module()

    class _Proc:
        returncode = 0
        stdout = "usage: llama-server --gpu-layers --flash-attn\nCUDA backend"
        stderr = ""

    monkeypatch.setattr(setup.shutil, "which", lambda _name: "/tmp/llama-server")
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: _Proc())

    assert setup._llama_server_supports_gpu_backend() is True


def test_ensure_cuda_wheel_requires_gpu_offload(monkeypatch):
    setup = _load_setup_module()

    calls = []

    monkeypatch.setattr(setup.os.path, "exists", lambda _p: False)
    monkeypatch.setattr(setup, "_pip_install", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(setup, "_pip_install_prebuilt", lambda *a, **k: True)
    monkeypatch.setattr(setup, "_llama_cpp_supports_gpu_offload", lambda: False)
    monkeypatch.setattr(setup, "_has_llama_cpp_python", lambda: True)

    assert setup._ensure_cuda_wheel() is False
    assert any("nvidia-cuda-runtime-cu12" in args for args, _ in calls)
