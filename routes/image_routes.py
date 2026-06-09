"""Image generation routes — A1111 Stable Diffusion WebUI integration."""

import base64
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
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(400, "prompt is required")

        width = data.get("width", 512)
        height = data.get("height", 512)
        negative_prompt = (data.get("negative_prompt") or "").strip()
        defaults = get_setting("a1111_defaults", {})
        steps = data.get("steps") or defaults.get("steps", 20)
        cfg_scale = data.get("cfg_scale") or defaults.get("cfg_scale", 7)
        sampler_name = data.get("sampler_name") or defaults.get("sampler_name", "Euler a")

        a1111_base = (get_setting("a1111_api_base", "http://a1111:7860") or "http://a1111:7860").rstrip("/")

        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "sampler_name": sampler_name,
            "batch_size": 1,
            "n_iter": 1,
            "seed": -1,
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=30.0)) as client:
                resp = await client.post(f"{a1111_base}/sdapi/v1/txt2img", json=payload)
                if resp.status_code != 200:
                    error_text = resp.text[:500]
                    try:
                        err_json = resp.json()
                        error_text = err_json.get("detail", error_text) if isinstance(err_json.get("detail"), str) else error_text
                    except Exception:
                        pass
                    raise HTTPException(502, f"A1111 API error ({resp.status_code}): {error_text}")

                result = resp.json()
                images_b64 = result.get("images", [])
                if not images_b64:
                    raise HTTPException(502, "A1111 returned no images")

                raw_b64 = images_b64[0]
                if raw_b64.startswith("data:image"):
                    raw_b64 = raw_b64.split(",", 1)[1]

                img_dir = Path(GENERATED_IMAGES_DIR)
                img_dir.mkdir(parents=True, exist_ok=True)
                filename = f"{uuid.uuid4().hex[:12]}.png"
                img_path = img_dir / filename
                img_path.write_bytes(base64.b64decode(raw_b64))

                info = result.get("info", "")
                if isinstance(info, str):
                    try:
                        import json as _json
                        info = _json.loads(info)
                    except Exception:
                        info = {"raw": info}

                db = SessionLocal()
                try:
                    gallery = GalleryImage(
                        id=str(uuid.uuid4()),
                        filename=filename,
                        prompt=prompt,
                        model="A1111",
                        size=f"{width}x{height}",
                        quality="standard",
                        owner=user or "",
                    )
                    db.add(gallery)
                    db.commit()
                    image_id = gallery.id
                except Exception:
                    image_id = None
                finally:
                    db.close()

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
            logger.error(f"Image generation failed: {e}")
            raise HTTPException(500, f"Image generation failed: {str(e)}")

    return router
