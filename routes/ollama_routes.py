"""Ollama helper routes for Cookbook UX."""

import asyncio
import json
import os
import shlex
import shutil
import sys
import uuid
from pathlib import Path

import urllib.request
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.constants import BASE_DIR
from core.middleware import require_admin
from core.platform_compat import IS_APPLE_SILICON
from routes.cookbook_helpers import _validate_remote_host, _SSH_PORT_RE, run_ssh_command_async
from routes.shell_routes import TMUX_LOG_DIR, _running_in_container


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


def _write_ollama_pull_runner(runner_path: Path, log_path: Path, model: str, in_docker: bool) -> list[str]:
    """Write a shell runner script for ollama pull and return its lines."""
    if in_docker:
        pull_cmd = f"docker exec atenea-ollama ollama pull {shlex.quote(model)}"
    else:
        pull_cmd = f"ollama pull {shlex.quote(model)}"
    lines = [
        "#!/usr/bin/env bash",
        f"cd {shlex.quote(str(BASE_DIR))}",
        f"exec > >(tee -a {shlex.quote(str(log_path))}) 2>&1",
        pull_cmd,
        'EC=$?',
        'echo ":::EXIT_CODE:::${EC}"',
        'echo "=== Ollama pull complete ==="',
    ]
    runner_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    runner_path.chmod(0o755)
    return lines


def setup_ollama_routes() -> APIRouter:
    router = APIRouter(tags=["ollama"])

    class PullRequest(BaseModel):
        model: str
        host: str | None = None
        ssh_port: str | None = None

    @router.get("/api/ollama/catalog")
    async def ollama_catalog():
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

        session_id = f"ollama-pull-{uuid.uuid4().hex[:8]}"

        if host:
            # REMOTE: run `ollama pull` over SSH
            cmd = f"ollama pull {shlex.quote(model)}"
            rc, stdout_b, stderr_b = await run_ssh_command_async(
                host, req.ssh_port, cmd, timeout=1800,
            )
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
            return {"ok": rc == 0, "stdout": stdout[-4000:], "stderr": stderr[-4000:], "host": host, "session_id": session_id}

        # LOCAL: launch pull in a tmux session so the frontend can track progress
        in_docker = os.path.exists("/.dockerenv")
        TMUX_LOG_DIR.mkdir(parents=True, exist_ok=True)
        runner_path = TMUX_LOG_DIR / f"{session_id}.sh"
        log_path = TMUX_LOG_DIR / f"{session_id}.log"
        _write_ollama_pull_runner(runner_path, log_path, model, in_docker)

        setup_cmd = f"tmux new-session -d -s {session_id} {shlex.quote(str(runner_path))}"
        proc = await asyncio.create_subprocess_shell(
            setup_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()

        if proc.returncode != 0:
            stderr = (await proc.stderr.read()).decode(errors="replace")
            return {"ok": False, "error": stderr, "session_id": session_id}

        return {"ok": True, "session_id": session_id, "remote": "local"}

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

    @router.post("/api/ollama/native/install")
    async def ollama_native_install(request: Request):
        """Install Ollama natively on the host OS (no Docker container).

        macOS:  brew install ollama (no sudo, Metal GPU)
        Linux:  curl -fsSL https://ollama.com/install.sh | sh (auto-detects CUDA)

        Returns ``{"ok": true}`` on success, or ``{"ok": false, "manual_cmd": "…"}``
        when automatic install is not possible from the current environment.
        """
        require_admin(request)
        in_docker = _running_in_container()
        platform = sys.platform

        if platform == "darwin":
            if not in_docker:
                # Native macOS — install Homebrew if missing, then Ollama
                # NONINTERACTIVE=1 skips the password/SIP prompts.
                cmd = (
                    "if ! command -v brew &>/dev/null; then"
                    "  echo '[atenea] Homebrew not found — installing…';"
                    "  NONINTERACTIVE=1 /bin/bash -c"
                    "    \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                    "    </dev/null 2>&1 || { echo 'ERROR: Homebrew install failed'; exit 1; };"
                    "  echo '[atenea] Homebrew installed.';"
                    "fi;"
                    # Ensure brew is on PATH (Apple Silicon: /opt/homebrew/bin)
                    "eval \"$(brew shellenv 2>/dev/null || echo)\";"
                    "echo '[atenea] Installing ollama…';"
                    "brew install ollama && brew services start ollama"
                )
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "bash", "-lc", cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _out, _err = await asyncio.wait_for(proc.communicate(), timeout=300)
                    if proc.returncode == 0:
                        return {"ok": True, "detail": "Ollama installed via Homebrew"}
                    error = _err.decode("utf-8", errors="replace")[-500:]
                    return {"ok": False, "error": error, "manual_cmd": "brew install ollama && brew services start ollama"}
                except TimeoutError:
                    return {"ok": False, "error": "Install timed out (300s)", "manual_cmd": "brew install ollama && brew services start ollama"}
                except Exception as exc:
                    return {"ok": False, "error": str(exc), "manual_cmd": "brew install ollama && brew services start ollama"}
            else:
                # Docker on macOS — can't run brew from container
                return {
                    "ok": False,
                    "manual_cmd": (
                        "if ! command -v brew &>/dev/null; then "
                        'NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/null; '
                        "fi && brew install ollama && brew services start ollama"
                    ),
                    "error": (
                        "Atenea runs inside Docker on macOS. Install Ollama natively "
                        "on your Mac in a terminal for Metal GPU acceleration"
                    ),
                }

        # Linux (native or Docker)
        if in_docker:
            return {
                "ok": False,
                "manual_cmd": "curl -fsSL https://ollama.com/install.sh | sh",
                "error": (
                    "Atenea runs inside Docker. Install Ollama natively on the host "
                    "in a terminal for best performance (auto-detects CUDA):"
                ),
            }

        # Native Linux — run install script (needs passwordless sudo)
        cmd = "curl -fsSL https://ollama.com/install.sh | sh"
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash", "-lc", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _out, _err = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode == 0:
                return {"ok": True, "detail": "Ollama installed (curl | sh)"}
            error = _err.decode("utf-8", errors="replace")[-300:]
            manual_cmd = "curl -fsSL https://ollama.com/install.sh | sh"
            if "sudo" in error.lower() and ("password" in error.lower() or "no tty" in error.lower()):
                return {
                    "ok": False,
                    "error": "Install needs sudo — run manually in a terminal",
                    "manual_cmd": manual_cmd,
                }
            return {"ok": False, "error": error, "manual_cmd": manual_cmd}
        except TimeoutError:
            return {"ok": False, "error": "Install script timed out (120s)", "manual_cmd": "curl -fsSL https://ollama.com/install.sh | sh"}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "manual_cmd": "curl -fsSL https://ollama.com/install.sh | sh"}

    return router
