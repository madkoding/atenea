"""Regression guards for Notes DOM rendering helpers."""

from pathlib import Path

from tests.helpers.ast_check import assert_source_has

ROOT = Path(__file__).resolve().parents[1]


def test_notes_image_src_guard_rejects_script_capable_data_images():
    path = ROOT / "static" / "js" / "notes.js"

    assert_source_has(path, "function _safeImgSrc(s)")
    assert_source_has(path, r"^data:image\/(?:png|jpe?g|gif|webp);base64,")
    assert r"^data:image\/i.test(v)" not in path.read_text(encoding="utf-8")


def test_notes_linkify_escapes_href_attribute():
    path = ROOT / "static" / "js" / "notes.js"

    assert_source_has(path, "function _attrEsc(s)")
    assert_source_has(path, 'href="${_attrEsc(href)}"')
    assert 'href="${href}"' not in path.read_text(encoding="utf-8")


def test_notes_edit_form_uses_safe_image_src_guard():
    path = ROOT / "static" / "js" / "notes.js"

    assert_source_has(path, "let currentImageUrl = _safeImgSrc(note?.image_url || '');")
    assert_source_has(path, "let _stashedDrawUrl = (type === 'draw') ? (_safeImgSrc(note?.image_url) || null) : null;")
    assert_source_has(path, "_wireCanvas(bodyEl, _stashedDrawUrl || currentImageUrl || _safeImgSrc(note?.image_url) || null)")
    assert_source_has(path, "_wireCanvas(form.querySelector('.note-form-body'), _safeImgSrc(note?.image_url) || null)")
    assert_source_has(path, "const safeInitialImageUrl = _safeImgSrc(initialImageUrl);")
    assert_source_has(path, "img.src = safeInitialImageUrl;")
    assert "img.src = initialImageUrl;" not in path.read_text(encoding="utf-8")
