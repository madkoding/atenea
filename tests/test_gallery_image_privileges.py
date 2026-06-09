import ast
from pathlib import Path

from tests.helpers.ast_check import assert_contains_call

GATED_IMAGE_FUNCTIONS = {
    "gallery_ai_upscale",
    "gallery_style_transfer",
    "inpaint_proxy",
    "harmonize_image",
    "denoise_image",
    "upscale_image_local",
    "remove_background",
    "enhance_face",
}

GALLERY_ROUTES = Path(__file__).resolve().parents[1] / "routes" / "gallery_routes.py"


def _function_sources(source):
    tree = ast.parse(source)
    return {
        node.name: ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_image_generation_endpoints_require_image_privilege():
    source = GALLERY_ROUTES.read_text(encoding="utf-8")
    functions = _function_sources(source)

    for name in GATED_IMAGE_FUNCTIONS:
        assert name in functions
        assert 'require_privilege(request, "can_generate_images")' in functions[name]


def test_gallery_routes_imports_privilege_helper():
    assert_contains_call(GALLERY_ROUTES, "get_current_user")
    assert_contains_call(GALLERY_ROUTES, "require_privilege")
