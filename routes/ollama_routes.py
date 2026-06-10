"""Ollama helper routes for Cookbook UX."""

import asyncio
import json
import shlex
import shutil
import sys
import urllib.request
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.middleware import require_admin
from core.platform_compat import IS_APPLE_SILICON
from routes.cookbook_helpers import _validate_remote_host, _SSH_PORT_RE, run_ssh_command_async


_OLLAMA_API_BASES = (
    "http://127.0.0.1:11434",
    "http://localhost:11434",
    "http://host.docker.internal:11434",
)


def _ollama_api_pull(model: str, timeout: int = 1800) -> dict:
    """Pull a model using Ollama's HTTP API with streaming — no CLI binary needed.
    
    Uses stream=true so the connection stays alive with continuous progress
    updates (no silent timeout). Returns when the pull is complete.
    """
    import httpx

    for base in _OLLAMA_API_BASES:
        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream(
                    "POST",
                    f"{base}/api/pull",
                    json={"model": model, "stream": True},
                ) as resp:
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if data.get("status") == "success":
                                return {"ok": True, "detail": "success", "host": "local", "endpoint": f"{base}/v1"}
                        except json.JSONDecodeError:
                            continue
            return {"ok": False, "detail": "pull did not complete", "host": "local"}
        except httpx.ConnectError:
            continue
        except httpx.TimeoutException:
            continue
        except Exception:
            continue
    return {"ok": False, "detail": "Ollama API unreachable at 127.0.0.1:11434 / localhost / host.docker.internal", "host": "local"}


def setup_ollama_routes() -> APIRouter:
    router = APIRouter(tags=["ollama"])

    class PullRequest(BaseModel):
        model: str
        host: str | None = None
        ssh_port: str | None = None

    @router.get("/api/ollama/catalog")
    async def ollama_catalog(request: Request):
        require_admin(request)
        models = [
                # ── Qwen3.5 0.8B ──
                {"id": "qwen3.5:0.8b", "name": "Qwen3.5 0.8B", "family": "qwen", "size": "1.0GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:0.8b-q8_0", "name": "Qwen3.5 0.8B Q8_0", "family": "qwen", "size": "1.0GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:0.8b-bf16", "name": "Qwen3.5 0.8B BF16", "family": "qwen", "size": "1.8GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:0.8b-mlx", "name": "Qwen3.5 0.8B MLX", "family": "qwen", "size": "1.2GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:0.8b-mlx-bf16", "name": "Qwen3.5 0.8B MLX BF16", "family": "qwen", "size": "1.7GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:0.8b-mxfp8", "name": "Qwen3.5 0.8B MXFP8", "family": "qwen", "size": "1.2GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:0.8b-nvfp4", "name": "Qwen3.5 0.8B NVFP4", "family": "qwen", "size": "1.0GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                # ── Qwen3.5 2B ──
                {"id": "qwen3.5:2b", "name": "Qwen3.5 2B", "family": "qwen", "size": "2.7GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:2b-q4_K_M", "name": "Qwen3.5 2B Q4_K_M", "family": "qwen", "size": "1.9GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:2b-q8_0", "name": "Qwen3.5 2B Q8_0", "family": "qwen", "size": "2.7GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:2b-bf16", "name": "Qwen3.5 2B BF16", "family": "qwen", "size": "4.6GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:2b-mlx", "name": "Qwen3.5 2B MLX", "family": "qwen", "size": "3.1GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:2b-mlx-bf16", "name": "Qwen3.5 2B MLX BF16", "family": "qwen", "size": "4.4GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:2b-mxfp8", "name": "Qwen3.5 2B MXFP8", "family": "qwen", "size": "3.1GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:2b-nvfp4", "name": "Qwen3.5 2B NVFP4", "family": "qwen", "size": "2.5GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                # ── Qwen3.5 4B ──
                {"id": "qwen3.5:4b", "name": "Qwen3.5 4B", "family": "qwen", "size": "3.4GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:4b-q4_K_M", "name": "Qwen3.5 4B Q4_K_M", "family": "qwen", "size": "3.4GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:4b-q8_0", "name": "Qwen3.5 4B Q8_0", "family": "qwen", "size": "5.3GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:4b-bf16", "name": "Qwen3.5 4B BF16", "family": "qwen", "size": "9.3GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:4b-mlx", "name": "Qwen3.5 4B MLX", "family": "qwen", "size": "4.0GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:4b-mlx-bf16", "name": "Qwen3.5 4B MLX BF16", "family": "qwen", "size": "9.1GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:4b-mxfp8", "name": "Qwen3.5 4B MXFP8", "family": "qwen", "size": "5.6GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:4b-nvfp4", "name": "Qwen3.5 4B NVFP4", "family": "qwen", "size": "4.0GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                # ── Qwen3.5 9B ──
                {"id": "qwen3.5:9b", "name": "Qwen3.5 9B", "family": "qwen", "size": "6.6GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:9b-q4_K_M", "name": "Qwen3.5 9B Q4_K_M", "family": "qwen", "size": "6.6GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:9b-q8_0", "name": "Qwen3.5 9B Q8_0", "family": "qwen", "size": "11GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:9b-bf16", "name": "Qwen3.5 9B BF16", "family": "qwen", "size": "19GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:9b-mlx", "name": "Qwen3.5 9B MLX", "family": "qwen", "size": "8.9GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:9b-mlx-bf16", "name": "Qwen3.5 9B MLX BF16", "family": "qwen", "size": "19GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:9b-mxfp8", "name": "Qwen3.5 9B MXFP8", "family": "qwen", "size": "12GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:9b-nvfp4", "name": "Qwen3.5 9B NVFP4", "family": "qwen", "size": "8.9GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                # ── Qwen3.5 27B ──
                {"id": "qwen3.5:27b", "name": "Qwen3.5 27B", "family": "qwen", "size": "17GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:27b-q4_K_M", "name": "Qwen3.5 27B Q4_K_M", "family": "qwen", "size": "17GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "qwen3.5:27b-q8_0", "name": "Qwen3.5 27B Q8_0", "family": "qwen", "size": "30GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram+ram"},
                {"id": "qwen3.5:27b-bf16", "name": "Qwen3.5 27B BF16", "family": "qwen", "size": "56GB", "context": "256K", "modality": "Text, Image", "vram_hint": "unloadable"},
                {"id": "qwen3.5:27b-int4", "name": "Qwen3.5 27B INT4", "family": "qwen", "size": "16GB", "context": "256K", "modality": "Text", "vram_hint": "vram-only"},
                {"id": "qwen3.5:27b-int8", "name": "Qwen3.5 27B INT8", "family": "qwen", "size": "30GB", "context": "256K", "modality": "Text", "vram_hint": "vram+ram"},
                {"id": "qwen3.5:27b-mlx", "name": "Qwen3.5 27B MLX", "family": "qwen", "size": "20GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:27b-mlx-bf16", "name": "Qwen3.5 27B MLX BF16", "family": "qwen", "size": "55GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:27b-mxfp8", "name": "Qwen3.5 27B MXFP8", "family": "qwen", "size": "31GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:27b-nvfp4", "name": "Qwen3.5 27B NVFP4", "family": "qwen", "size": "20GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:27b-coding-mxfp8", "name": "Qwen3.5 27B Coding MXFP8", "family": "qwen", "size": "31GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:27b-coding-nvfp4", "name": "Qwen3.5 27B Coding NVFP4", "family": "qwen", "size": "20GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:27b-coding-bf16", "name": "Qwen3.5 27B Coding BF16", "family": "qwen", "size": "55GB", "context": "256K", "modality": "Text", "vram_hint": "unloadable"},
                # ── Qwen3.5 35B MoE ──
                {"id": "qwen3.5:35b-a3b", "name": "Qwen3.5 35B-A3B", "family": "qwen", "size": "24GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram+ram"},
                {"id": "qwen3.5:35b-a3b-q4_K_M", "name": "Qwen3.5 35B-A3B Q4_K_M", "family": "qwen", "size": "24GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram+ram"},
                {"id": "qwen3.5:35b-a3b-q8_0", "name": "Qwen3.5 35B-A3B Q8_0", "family": "qwen", "size": "39GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram+ram"},
                {"id": "qwen3.5:35b-a3b-bf16", "name": "Qwen3.5 35B-A3B BF16", "family": "qwen", "size": "72GB", "context": "256K", "modality": "Text, Image", "vram_hint": "unloadable"},
                {"id": "qwen3.5:35b-a3b-int4", "name": "Qwen3.5 35B-A3B INT4", "family": "qwen", "size": "20GB", "context": "256K", "modality": "Text", "vram_hint": "vram-only"},
                {"id": "qwen3.5:35b-a3b-int8", "name": "Qwen3.5 35B-A3B INT8", "family": "qwen", "size": "38GB", "context": "256K", "modality": "Text", "vram_hint": "vram+ram"},
                {"id": "qwen3.5:35b-a3b-mlx", "name": "Qwen3.5 35B-A3B MLX", "family": "qwen", "size": "22GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:35b-a3b-mlx-bf16", "name": "Qwen3.5 35B-A3B MLX BF16", "family": "qwen", "size": "70GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:35b-a3b-mxfp8", "name": "Qwen3.5 35B-A3B MXFP8", "family": "qwen", "size": "38GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:35b-a3b-nvfp4", "name": "Qwen3.5 35B-A3B NVFP4", "family": "qwen", "size": "22GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:35b-a3b-coding-mxfp8", "name": "Qwen3.5 35B Coding MXFP8", "family": "qwen", "size": "38GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:35b-a3b-coding-nvfp4", "name": "Qwen3.5 35B Coding NVFP4", "family": "qwen", "size": "22GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                {"id": "qwen3.5:35b-a3b-coding-bf16", "name": "Qwen3.5 35B Coding BF16", "family": "qwen", "size": "70GB", "context": "256K", "modality": "Text", "vram_hint": "unloadable"},
                # ── Qwen3.5 122B MoE ──
                {"id": "qwen3.5:122b-a10b", "name": "Qwen3.5 122B-A10B", "family": "qwen", "size": "81GB", "context": "256K", "modality": "Text, Image", "vram_hint": "unloadable"},
                {"id": "qwen3.5:122b-a10b-q4_K_M", "name": "Qwen3.5 122B-A10B Q4_K_M", "family": "qwen", "size": "81GB", "context": "256K", "modality": "Text, Image", "vram_hint": "unloadable"},
                {"id": "qwen3.5:35b", "name": "Qwen3.5 35B (dense)", "family": "qwen", "size": "24GB", "context": "256K", "modality": "Text, Image", "vram_hint": "vram+ram"},
                {"id": "qwen3.5:35b-mlx", "name": "Qwen3.5 35B MLX", "family": "qwen", "size": "22GB", "context": "256K", "modality": "Text", "vram_hint": "unified-memory"},
                # ── Other popular models ──
                {"id": "llama3.2:3b", "name": "Llama 3.2 3B", "family": "llama"},
                {"id": "llama3.2:1b", "name": "Llama 3.2 1B", "family": "llama"},
                {"id": "llama3.3:70b", "name": "Llama 3.3 70B", "family": "llama", "size": "40GB", "context": "128K", "modality": "Text", "vram_hint": "vram+ram"},
                {"id": "qwen2.5:7b", "name": "Qwen 2.5 7B", "family": "qwen", "size": "4.1GB", "context": "32K", "modality": "Text", "vram_hint": "vram-only"},
                {"id": "qwen2.5:14b", "name": "Qwen 2.5 14B", "family": "qwen", "size": "8.9GB", "context": "32K", "modality": "Text", "vram_hint": "vram-only"},
                {"id": "qwen2.5:32b", "name": "Qwen 2.5 32B", "family": "qwen", "size": "20GB", "context": "32K", "modality": "Text", "vram_hint": "vram-only"},
                {"id": "gemma3:4b", "name": "Gemma 3 4B", "family": "gemma", "size": "2.5GB", "context": "128K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "gemma3:12b", "name": "Gemma 3 12B", "family": "gemma", "size": "8.0GB", "context": "128K", "modality": "Text, Image", "vram_hint": "vram-only"},
                {"id": "deepseek-r1:8b", "name": "DeepSeek R1 8B", "family": "deepseek", "size": "4.9GB", "context": "128K", "modality": "Text", "vram_hint": "vram-only"},
                {"id": "deepseek-r1:14b", "name": "DeepSeek R1 14B", "family": "deepseek", "size": "9.0GB", "context": "128K", "modality": "Text", "vram_hint": "vram-only"},
                {"id": "deepseek-r1:70b", "name": "DeepSeek R1 70B", "family": "deepseek", "size": "42GB", "context": "128K", "modality": "Text", "vram_hint": "vram+ram"},
                {"id": "mistral:7b", "name": "Mistral 7B", "family": "mistral", "size": "4.1GB", "context": "32K", "modality": "Text", "vram_hint": "vram-only"},
                {"id": "mistral-nemo:12b", "name": "Mistral Nemo 12B", "family": "mistral", "size": "7.5GB", "context": "128K", "modality": "Text", "vram_hint": "vram-only"},
                {"id": "mixtral:8x7b", "name": "Mixtral 8x7B", "family": "mistral", "size": "26GB", "context": "32K", "modality": "Text", "vram_hint": "vram+ram"},
                {"id": "phi3:14b", "name": "Phi-3 14B", "family": "phi", "size": "8.0GB", "context": "128K", "modality": "Text", "vram_hint": "vram-only"},
        ]
        if not IS_APPLE_SILICON:
            models = [m for m in models if m.get("vram_hint") != "unified-memory"]
        return {"models": models}

    @router.post("/api/ollama/pull")
    async def ollama_pull(request: Request, req: PullRequest):
        require_admin(request)
        model = (req.model or "").strip()
        if not model:
            raise HTTPException(400, "model is required")

        host = _validate_remote_host(req.host)
        if req.ssh_port is not None and req.ssh_port != "" and not _SSH_PORT_RE.fullmatch(str(req.ssh_port)):
            raise HTTPException(400, "Invalid ssh_port")

        if host:
            cmd = f"ollama pull {shlex.quote(model)}"
            rc, stdout_b, stderr_b = await run_ssh_command_async(
                host,
                req.ssh_port,
                cmd,
                timeout=1800,
            )
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
            return {"ok": rc == 0, "stdout": stdout[-4000:], "stderr": stderr[-4000:], "host": host}

        result = await asyncio.to_thread(_ollama_api_pull, model)
        return result

    @router.get("/api/ollama/models")
    async def ollama_models(request: Request, host: str | None = None, ssh_port: str | None = None):
        require_admin(request)
        remote = _validate_remote_host(host)
        if ssh_port is not None and ssh_port != "" and not _SSH_PORT_RE.fullmatch(str(ssh_port)):
            raise HTTPException(400, "Invalid ssh_port")

        if remote:
            rc, stdout_b, _stderr_b = await run_ssh_command_async(
                remote,
                ssh_port,
                "python3 - <<'PY'\n"
                "import json,urllib.request\n"
                "urls=['http://127.0.0.1:11434/api/tags','http://localhost:11434/api/tags']\n"
                "data={'models': []}\n"
                "for u in urls:\n"
                "  try:\n"
                "    with urllib.request.urlopen(u, timeout=3) as r:\n"
                "      data=json.loads(r.read().decode('utf-8','replace'))\n"
                "      break\n"
                "  except Exception:\n"
                "    pass\n"
                "print(json.dumps(data))\n"
                "PY",
                timeout=8,
            )
            if rc != 0:
                return {"models": [], "host": remote}
            try:
                payload = json.loads(stdout_b.decode("utf-8", errors="replace").strip() or "{}")
            except Exception:
                payload = {}
            models = payload.get("models") if isinstance(payload, dict) else []
            return {"models": models if isinstance(models, list) else [], "host": remote}

        models = []
        if shutil.which("ollama"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ollama",
                    "list",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                out_b, _err_b = await asyncio.wait_for(proc.communicate(), timeout=5)
                lines = out_b.decode("utf-8", errors="replace").splitlines()
                for line in lines[1:]:
                    parts = line.split()
                    if not parts:
                        continue
                    models.append({"name": parts[0], "model": parts[0]})
            except Exception:
                pass
        if not models:
            for url in (
                "http://127.0.0.1:11434/api/tags",
                "http://localhost:11434/api/tags",
                "http://host.docker.internal:11434/api/tags",
            ):
                try:
                    import urllib.request

                    with urllib.request.urlopen(url, timeout=2) as r:
                        payload = json.loads(r.read().decode("utf-8", errors="replace"))
                    models = payload.get("models") if isinstance(payload, dict) else []
                    if isinstance(models, list):
                        break
                except Exception:
                    continue
        return {"models": models if isinstance(models, list) else [], "host": "local"}

    return router
