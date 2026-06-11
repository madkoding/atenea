import logging
import os

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

_OLLAMA_CONTAINER = "atenea-ollama"
_OLLAMA_IMAGE = "docker.io/ollama/ollama:latest"
_OLLAMA_PORT = int(os.environ.get("OLLAMA_PORT", "11434"))
_OLLAMA_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ollama")


def _compute_ollama_env():
    """Auto-calculate Ollama performance env vars based on detected hardware."""
    try:
        from services.hwfit.hardware import detect_system
        hw = detect_system()
    except Exception:
        hw = {}

    total_ram = hw.get("total_ram_gb") or 0
    available_ram = hw.get("available_ram_gb") or 0
    cpu_cores = hw.get("cpu_cores") or 0
    has_gpu = hw.get("has_gpu", False)
    gpu_vram = hw.get("gpu_vram_gb") or 0
    unified = hw.get("unified_memory", False)

    # Effective memory: discrete GPUs have dedicated VRAM, unified shares RAM
    if has_gpu and not unified:
        effective_mem = min(available_ram, gpu_vram)
    else:
        effective_mem = available_ram

    env = {}

    if cpu_cores >= 16 and effective_mem >= 32:
        env["OLLAMA_NUM_PARALLEL"] = "4"
    elif cpu_cores >= 8 and effective_mem >= 16:
        env["OLLAMA_NUM_PARALLEL"] = "2"
    elif has_gpu:
        env["OLLAMA_NUM_PARALLEL"] = "2"
    else:
        env["OLLAMA_NUM_PARALLEL"] = "1"

    if effective_mem >= 32:
        env["OLLAMA_MAX_LOADED_MODELS"] = "3"
    elif effective_mem >= 16:
        env["OLLAMA_MAX_LOADED_MODELS"] = "2"
    else:
        env["OLLAMA_MAX_LOADED_MODELS"] = "1"

    if effective_mem >= 32:
        env["OLLAMA_KEEP_ALIVE"] = "5m"
    elif effective_mem >= 16:
        env["OLLAMA_KEEP_ALIVE"] = "2m"
    elif effective_mem >= 8:
        env["OLLAMA_KEEP_ALIVE"] = "1m"
    else:
        env["OLLAMA_KEEP_ALIVE"] = "30s"

    logger.info("Auto-calculated Ollama env: %s", env)
    return env


def _docker_client():
    try:
        import docker
        return docker.from_env()
    except Exception as exc:
        logger.warning("Docker not available: %s", exc)
        return None


def _find_ollama_container(client):
    try:
        containers = client.containers.list(all=True, filters={"name": _OLLAMA_CONTAINER})
        for c in containers:
            if c.name == _OLLAMA_CONTAINER:
                return c
    except Exception:
        pass
    return None


def _get_container_state(client):
    """Return dict with container status or None."""
    container = _find_ollama_container(client)
    if container is None:
        return {"status": "absent", "container_name": _OLLAMA_CONTAINER}
    state = container.attrs.get("State", {})
    return {
        "status": state.get("Status", "unknown"),
        "running": state.get("Running", False),
        "container_name": _OLLAMA_CONTAINER,
        "container_id": container.short_id,
        "started_at": state.get("StartedAt", ""),
    }


def setup_docker_ollama_routes():
    router = APIRouter(prefix="/api/docker/ollama")

    @router.get("/status")
    async def status():
        client = _docker_client()
        if client is None:
            return {"status": "docker_unavailable", "container_name": _OLLAMA_CONTAINER}
        try:
            return _get_container_state(client)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/start")
    async def start():
        client = _docker_client()
        if client is None:
            raise HTTPException(status_code=503, detail="Docker socket not available")
        try:
            container = _find_ollama_container(client)
            if container:
                if container.status == "running":
                    return {"status": "already_running", "container_name": _OLLAMA_CONTAINER}
                container.start()
                container.reload()
                return _get_container_state(client)

            # Pull image if needed (lightweight, fast if cached)
            try:
                client.images.get(_OLLAMA_IMAGE)
            except Exception:
                logger.info("Pulling Ollama Docker image...")
                client.images.pull(_OLLAMA_IMAGE)

            env = {"OLLAMA_HOST": f"0.0.0.0:{_OLLAMA_PORT}"}
            env.update(_compute_ollama_env())
            container = client.containers.run(
                image=_OLLAMA_IMAGE,
                name=_OLLAMA_CONTAINER,
                detach=True,
                restart_policy={"Name": "unless-stopped"},
                ports={"11434/tcp": ("0.0.0.0", _OLLAMA_PORT)},
                volumes={"atenea_ollama_data": {"bind": "/root/.ollama", "mode": "rw"}},
                environment=env,
            )
            container.reload()
            return _get_container_state(client)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/stop")
    async def stop():
        client = _docker_client()
        if client is None:
            raise HTTPException(status_code=503, detail="Docker socket not available")
        try:
            container = _find_ollama_container(client)
            if container is None or container.status != "running":
                return {"status": "not_running", "container_name": _OLLAMA_CONTAINER}
            container.stop()
            return {"status": "stopped", "container_name": _OLLAMA_CONTAINER}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return router
