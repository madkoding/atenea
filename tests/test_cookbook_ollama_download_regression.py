from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_manual_download_input_accepts_explicit_ollama_prefix():
    src = _read("static/js/cookbook.js")
    assert "rawInput.toLowerCase().startsWith('ollama:')" in src
    assert "_startOllamaPull" in src


def test_manual_ollama_pull_validates_model_id_and_reuses_runner_flow():
    src = _read("static/js/cookbook.js")
    assert "_OLLAMA_MODEL_ID_RE" in src
    assert "cmd = `ollama pull ${trimmed}`" in src
    assert "fetch('/api/model/serve'" in src


def test_dependency_install_reports_noninteractive_sudo_block_clearly():
    src = _read("static/js/cookbook.js")
    assert "requires sudo, but this session is non-interactive" in src
    assert "Cookbook cannot prompt for password" in src


def test_download_panel_ollama_builder_preserves_exact_model_id():
    src = _read("static/js/cookbookDownload.js")
    assert "const modelId = String(model?.repo_id || model?.name || '').trim();" in src
    assert "cmd = `ollama pull ${modelId}`;" in src
    assert "model.name.split('/').pop().toLowerCase()" not in src
