"""Image generation routes — A1111 Stable Diffusion WebUI integration."""

import base64
import json
import logging
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from src.auth.helpers import get_current_user, require_privilege
from src.constants import GENERATED_IMAGES_DIR
from src.settings import get_setting

from core.database import SessionLocal, GalleryImage

logger = logging.getLogger(__name__)


def _a1111_base_url() -> str:
    return (get_setting("a1111_api_base", "http://a1111:7860") or "http://a1111:7860").rstrip("/")


def _a1111_payload(data: dict) -> dict:
    defaults = get_setting("a1111_defaults", {})
    return {
        "prompt": (data.get("prompt") or "").strip(),
        "negative_prompt": (data.get("negative_prompt") or "").strip(),
        "width": data.get("width", 512),
        "height": data.get("height", 512),
        "steps": data.get("steps") or defaults.get("steps", 20),
        "cfg_scale": data.get("cfg_scale") or defaults.get("cfg_scale", 7),
        "sampler_name": data.get("sampler_name") or defaults.get("sampler_name", "Euler a"),
        "batch_size": 1,
        "n_iter": 1,
        "seed": -1,
    }


def _a1111_error_text(resp) -> str:
    error_text = resp.text[:500]
    try:
        err_json = resp.json()
    except Exception:
        return error_text
    detail = err_json.get("detail") if isinstance(err_json, dict) else None
    if isinstance(detail, str):
        return detail
    return error_text


def _first_image_b64(result: dict) -> str:
    images_b64 = result.get("images", [])
    if not images_b64:
        raise HTTPException(502, "A1111 returned no images")
    raw_b64 = images_b64[0]
    if isinstance(raw_b64, str) and raw_b64.startswith("data:image"):
        return raw_b64.split(",", 1)[1]
    return raw_b64


def _parse_info(info):
    if isinstance(info, str):
        try:
            return json.loads(info)
        except Exception:
            return {"raw": info}
    return info


def _save_generated_png(raw_b64: str) -> str:
    img_dir = Path(GENERATED_IMAGES_DIR)
    img_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:12]}.png"
    img_path = img_dir / filename
    img_path.write_bytes(base64.b64decode(raw_b64))
    return filename


def _store_gallery_image(filename: str, prompt: str, width, height, owner: str) -> str | None:
    db = SessionLocal()
    try:
        gallery = GalleryImage(
            id=str(uuid.uuid4()),
            filename=filename,
            prompt=prompt,
            model="A1111",
            size=f"{width}x{height}",
            quality="standard",
            owner=owner or "",
        )
        db.add(gallery)
        db.commit()
        return gallery.id
    except Exception:
        return None
    finally:
        db.close()


def setup_image_routes() -> APIRouter:
    router = APIRouter(tags=["images"])

    @router.post("/api/images/generate")
    async def generate_image(request: Request):
        """Generate an image via A1111's txt2img API."""
        user = get_current_user(request)
        if user:
            require_privilege(request, "can_generate_images")

        if not get_setting("a1111_enabled", False):
            raise HTTPException(503, "A1111 image generation is not enabled. Set a1111_enabled=true in settings and ensure the A1111 container is running.")

        data = await request.json()
        payload = _a1111_payload(data)
        prompt = payload["prompt"]
        if not prompt:
            raise HTTPException(400, "prompt is required")
        width = payload["width"]
        height = payload["height"]
        a1111_base = _a1111_base_url()

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=30.0)) as client:
                resp = await client.post(f"{a1111_base}/sdapi/v1/txt2img", json=payload)
                if resp.status_code != 200:
                    raise HTTPException(502, f"A1111 API error ({resp.status_code}): {_a1111_error_text(resp)}")

                result = resp.json()
                filename = _save_generated_png(_first_image_b64(result))
                info = _parse_info(result.get("info", ""))
                image_id = _store_gallery_image(filename, prompt, width, height, user or "")

                _pub_base = (get_setting("app_public_url", "") or "").rstrip("/")
                image_url = f"{_pub_base}/api/generated-image/{filename}"

                return {
                    "image_url": image_url,
                    "filename": filename,
                    "image_id": image_id,
                    "width": width,
                    "height": height,
                    "seed": info.get("seed", -1) if isinstance(info, dict) else -1,
                    "prompt": prompt,
                }

        except httpx.TimeoutException:
            raise HTTPException(504, "A1111 API timed out after 300s")
        except httpx.ConnectError:
            raise HTTPException(502, f"Cannot connect to A1111 at {a1111_base}. Is the container running?")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Image generation failed: {e}", exc_info=True)
            raise HTTPException(500, "Image generation failed")

    return router
