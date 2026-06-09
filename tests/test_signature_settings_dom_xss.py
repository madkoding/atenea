"""Regression guards for DOM attribute sinks in signature/settings UI."""

from pathlib import Path

from tests.helpers.ast_check import assert_source_has

ROOT = Path(__file__).resolve().parents[1]


def test_signature_picker_allows_only_raster_data_urls():
    path = ROOT / "static" / "js" / "signature.js"

    assert_source_has(path, "function _safeSignatureDataUrl(raw)")
    assert_source_has(path, r"^data:image\/png;base64,")
    assert_source_has(path, '<img src="${_esc(dataUrl)}"/>')
    assert 'dataUrl: s.data_url' not in path.read_text(encoding="utf-8")


def test_settings_2fa_setup_escapes_secret_and_qr_src():
    path = ROOT / "static" / "js" / "settings.js"

    assert_source_has(path, "function safeRasterDataUrl(raw)")
    assert_source_has(path, "const qrCode = safeRasterDataUrl(setup.qr_code);")
    assert_source_has(path, '<img src="${esc(qrCode)}"')
    assert_source_has(path, "${esc(setup.secret)}")
    assert 'src="${setup.qr_code}"' not in path.read_text(encoding="utf-8")
    assert '>${setup.secret}</div>' not in path.read_text(encoding="utf-8")
