"""Regression guards for API-provided research source hrefs."""

from pathlib import Path

from tests.helpers.ast_check import assert_source_has

ROOT = Path(__file__).resolve().parents[1]


def test_document_library_research_preview_whitelists_source_hrefs():
    path = ROOT / "static" / "js" / "documentLibrary.js"

    assert_source_has(path, "function _safeResearchHref(raw)")
    assert_source_has(path, "parsed.protocol === 'http:' || parsed.protocol === 'https:'")
    assert_source_has(path, "const url = _safeResearchHref(src.url);")
    assert 'href="${_esc(url)}"' not in path.read_text(encoding="utf-8")
    assert_source_has(path, "Failed to load: ${_esc(e.message)}")
    assert 'Failed to load: ${e.message}' not in path.read_text(encoding="utf-8")


def test_research_panel_whitelists_source_hrefs():
    path = ROOT / "static" / "js" / "research" / "panel.js"

    assert_source_has(path, "function _safeSourceHref(raw)")
    assert_source_has(path, "parsed.protocol === 'http:' || parsed.protocol === 'https:'")
    assert_source_has(path, "const url = _safeSourceHref(s.url);")
    assert "const url = _esc(s.url || '');" not in path.read_text(encoding="utf-8")
