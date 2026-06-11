import logging
import os

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

_OLLAMA_CONTAINER = "atenea-ollama"
_OLLAMA_IMAGE = "docker.io/ollama/ollama:latest"
_OLLAMA_PORT = int(os.environ.get("OLLAMA_PORT", "11434"))
_OLLAMA_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ollama")


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

            os.makedirs(_OLLAMA_DATA_DIR, exist_ok=True)
            container = client.containers.run(
                image=_OLLAMA_IMAGE,
                name=_OLLAMA_CONTAINER,
                detach=True,
                remove=True,
                restart_policy={"Name": "unless-stopped"},
                ports={"11434/tcp": ("0.0.0.0", _OLLAMA_PORT)},
                volumes={_OLLAMA_DATA_DIR: {"bind": "/root/.ollama", "mode": "rw"}},
                environment={"OLLAMA_HOST": f"0.0.0.0:{_OLLAMA_PORT}"},
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
