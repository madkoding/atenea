"""Regression guards for markdown raw-HTML sanitizer helpers."""

from pathlib import Path

from tests.helpers.ast_check import assert_source_has

ROOT = Path(__file__).resolve().parents[1]


def test_markdown_raw_html_sanitizer_checks_url_attr_edge_cases():
    path = ROOT / "static" / "js" / "markdown.js"

    assert_source_has(path, "function _compactUrlSchemeValue(value)")
    assert_source_has(path, "function _isDangerousUrl(value)")
    assert_source_has(path, "function _isDangerousSrcset(value)")
    assert_source_has(path, "'srcset'")
    assert_source_has(path, "candidate => _isDangerousUrl(candidate)")
    assert_source_has(path, "name === 'srcset' ? _isDangerousSrcset(attr.value) : _isDangerousUrl(attr.value)")


def test_markdown_raw_html_sanitizer_strips_scriptable_css():
    path = ROOT / "static" / "js" / "markdown.js"

    assert_source_has(path, "if (name === 'style')")
    assert_source_has(path, r"javascript:|vbscript:|data:|expression\(")
    assert_source_has(path, "el.removeAttribute(attr.name);")
