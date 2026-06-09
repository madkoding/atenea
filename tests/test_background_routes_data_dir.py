import os
from pathlib import Path


def test_background_routes_uses_upload_dir_constant_in_source():
    source = Path("routes/background_routes.py").read_text(encoding="utf-8")

    assert 'from src.constants import UPLOAD_DIR' in source
    assert 'os.path.join("data", "uploads", "backgrounds")' not in source


def test_background_dir_resolves_under_upload_dir():
    import routes.background_routes as background_routes

    assert background_routes.BACKGROUNDS_DIR == os.path.join(
        background_routes.UPLOAD_DIR,
        "backgrounds",
    )
