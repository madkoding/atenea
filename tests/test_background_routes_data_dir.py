import os
from pathlib import Path

from tests.helpers.ast_check import assert_source_does_not_have, assert_source_has

ROUTES = Path(__file__).resolve().parents[1] / "routes" / "background_routes.py"


def test_background_routes_uses_upload_dir_constant_in_source():
    assert_source_has(ROUTES, 'from src.constants import UPLOAD_DIR')
    assert_source_does_not_have(ROUTES, 'os.path.join("data", "uploads", "backgrounds")')


def test_background_dir_resolves_under_upload_dir():
    import routes.background_routes as background_routes

    assert background_routes.BACKGROUNDS_DIR == os.path.join(
        background_routes.UPLOAD_DIR,
        "backgrounds",
    )
