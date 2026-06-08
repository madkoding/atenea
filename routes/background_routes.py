"""Custom background image upload — user-supplied background images stored under DATA_DIR/uploads/backgrounds/."""
import os
import re
from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

BACKGROUNDS_DIR = os.path.join("data", "uploads", "backgrounds")
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_SAFE_NAME = re.compile(r'^[\w.\- ]+$', re.UNICODE)


def _sanitize_filename(name: str) -> str:
    name = os.path.basename(name).strip()
    if not _SAFE_NAME.match(name):
        raise HTTPException(400, "Invalid filename")
    return name


def _allowed_file(name: str) -> bool:
    ext = os.path.splitext(name)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def setup_background_routes():
    router = APIRouter(prefix="/api/backgrounds", tags=["backgrounds"])

    @router.get("/list")
    async def list_backgrounds():
        """Return list of uploaded background images."""
        os.makedirs(BACKGROUNDS_DIR, exist_ok=True)
        files = []
        for f in sorted(os.listdir(BACKGROUNDS_DIR)):
            path = os.path.join(BACKGROUNDS_DIR, f)
            if os.path.isfile(path) and _allowed_file(f):
                ext = os.path.splitext(f)[1].lower()
                files.append({
                    "name": f,
                    "url": f"/api/backgrounds/serve/{f}",
                    "size": os.path.getsize(path),
                    "ext": ext.lstrip('.'),
                })
        return {"backgrounds": files}

    @router.post("/upload")
    async def upload_background(request: Request, file: UploadFile = File(...)):
        if not file.filename or not _allowed_file(file.filename):
            raise HTTPException(400, "Only PNG, JPG, GIF, WebP, and SVG are allowed")
        safe = _sanitize_filename(file.filename)
        os.makedirs(BACKGROUNDS_DIR, exist_ok=True)
        dest = os.path.join(BACKGROUNDS_DIR, safe)
        if os.path.exists(dest):
            name_stem = os.path.splitext(safe)[0]
            ext = os.path.splitext(safe)[1]
            counter = 1
            while os.path.exists(os.path.join(BACKGROUNDS_DIR, f"{name_stem}_{counter}{ext}")):
                counter += 1
            dest = os.path.join(BACKGROUNDS_DIR, f"{name_stem}_{counter}{ext}")
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(400, "File too large (max 10 MB)")
        with open(dest, "wb") as f:
            f.write(content)
        return {"name": os.path.basename(dest), "url": f"/api/backgrounds/serve/{os.path.basename(dest)}"}

    @router.delete("/{name}")
    async def delete_background(request: Request, name: str):
        safe = _sanitize_filename(name)
        path = os.path.join(BACKGROUNDS_DIR, safe)
        if not os.path.isfile(path):
            raise HTTPException(404, "Background not found")
        os.remove(path)
        return {"status": "deleted", "name": safe}

    @router.get("/serve/{name}")
    async def serve_background(name: str):
        safe = _sanitize_filename(name)
        path = os.path.join(BACKGROUNDS_DIR, safe)
        if not os.path.isfile(path):
            raise HTTPException(404, "Background not found")
        ext = os.path.splitext(name)[1].lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
        }
        return FileResponse(path, media_type=mime_map.get(ext, "application/octet-stream"))

    return router
