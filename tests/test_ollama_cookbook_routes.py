from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_app_registers_ollama_routes():
    src = _read("app.py")
    assert "from routes.ollama_routes import setup_ollama_routes" in src
    assert "app.include_router(setup_ollama_routes())" in src


def test_ollama_routes_expose_catalog_and_pull_endpoints():
    src = _read("routes/ollama_routes.py")
    assert '@router.get("/api/ollama/catalog")' in src
    assert '@router.post("/api/ollama/pull")' in src
    assert '@router.get("/api/ollama/models")' in src


def test_serve_tab_uses_ollama_catalog_for_click_to_pull():
    src = _read("static/js/cookbookServe.js")
    assert "_fetchOllamaCatalog" in src
    assert "_renderOllamaCatalogSection" in src
    assert "_triggerOllamaPull" in src
    assert "fetch('/api/ollama/pull'" in src


def test_serve_tab_merges_catalog_with_installed_ollama_models():
    src = _read("static/js/cookbookServe.js")
    assert "fetch('/api/ollama/catalog'" in src
    assert "const installedSet = new Set(installed);" in src
    assert "out.push({" in src
    assert "installed: installedSet.has(id)" in src


def test_serve_tab_marks_installed_ollama_models_in_quick_pull_ui():
    src = _read("static/js/cookbookServe.js")
    assert "'local'" in src or "(local)" in src


def test_serve_tab_calls_ollama_pull_via_api():
    src = _read("static/js/cookbookServe.js")
    assert "_triggerOllamaPull" in src
    assert "fetch('/api/ollama/pull'" in src
    assert "uiModule.showToast('Ollama pull failed:" in src


def test_ollama_catalog_includes_vram_and_metadata_fields():
    src = _read("routes/ollama_routes.py")
    assert '"vram_hint"' in src
    assert '"size"' in src
    assert '"context"' in src
    assert '"modality"' in src
    assert '"vram-only"' in src
    assert '"vram+ram"' in src
    assert '"unloadable"' in src
    assert '"unified-memory"' in src


def test_ollama_catalog_includes_qwen3_5_family():
    src = _read("routes/ollama_routes.py")
    assert "qwen3.5:0.8b" in src
    assert "qwen3.5:2b" in src
    assert "qwen3.5:4b" in src
    assert "qwen3.5:9b" in src
    assert "qwen3.5:27b" in src
    assert "qwen3.5:35b-a3b" in src


def test_serve_tab_passes_through_vram_hint():
    src = _read("static/js/cookbookServe.js")
    assert "vram_hint:" in src
    assert "size:" in src
    assert "context:" in src
    assert "modality:" in src


def test_serve_tab_renders_vram_badge():
    src = _read("static/js/cookbookServe.js")
    assert "_renderVramBadge" in src
    assert "'vram-only'" in src
    assert "'vram+ram'" in src
    assert "'unloadable'" in src
    assert "'unified-memory'" in src


def test_serve_tab_renders_table_not_chips():
    src = _read("static/js/cookbookServe.js")
    assert "createElement('table')" in src
    assert "createElement('thead')" in src
    assert "'Model'" in src
    assert "'Size'" in src
    assert "'Context'" in src
    assert "'Modality'" in src
    assert "'VRAM'" in src


def test_ollama_pull_uses_http_api_not_cli():
    src = _read("routes/ollama_routes.py")
    assert "_ollama_api_pull" in src
    assert "/api/pull" in src
    assert '"stream": True' in src
    assert "asyncio.to_thread(_ollama_api_pull" in src


def test_ollama_catalog_filters_mlx_on_non_mac():
    src = _read("routes/ollama_routes.py")
    assert "IS_APPLE_SILICON" in src
    assert '!= "unified-memory"' in src
