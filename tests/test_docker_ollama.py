"""Tests for docker_ollama routes — container lifecycle via Docker SDK.

Because Docker may not be available in CI or on all dev machines, the
tests use monkeypatched docker client. The endpoint logic is still
exercised: start/stop/status, container-not-found, and error handling.
"""

import pytest


@pytest.fixture
def fake_docker_client():
    """Return a controllable fake docker client (dict-based)."""

    class _FakeContainer:
        def __init__(self, container_id, name, status="exited", attrs=None):
            self.short_id = container_id
            self.name = name
            self.status = status
            self.attrs = attrs or {
                "State": {"Status": status, "Running": status == "running", "StartedAt": ""}
            }

        def reload(self):
            pass

        def start(self):
            self.status = "running"
            self.attrs["State"]["Status"] = "running"
            self.attrs["State"]["Running"] = True

        def stop(self):
            self.status = "exited"
            self.attrs["State"]["Status"] = "exited"
            self.attrs["State"]["Running"] = False

    class _FakeImage:
        def __init__(self, tag):
            self.tags = [tag]

    class _FakeImages:
        def get(self, name):
            if "ollama" in name:
                return _FakeImage(name)
            raise Exception("Image not found")

        def pull(self, name):
            return _FakeImage(name)

    class _FakeContainers:
        def __init__(self):
            self._store = {}

        def list(self, all=False, filters=None):
            name_filter = (filters or {}).get("name", "")
            return [
                c for c in self._store.values()
                if not name_filter or name_filter in c.name
            ]

        def run(self, image, **kwargs):
            cid = f"cid-{len(self._store) + 1}"
            c = _FakeContainer(cid, kwargs.get("name", "unknown"), "running")
            self._store[c.name] = c
            return c

    class _FakeClient:
        def __init__(self):
            self.containers = _FakeContainers()
            self.images = _FakeImages()

        def from_env(self):
            return self

    fc = _FakeClient()
    # Pre-create the ollama container in "running" state for some tests
    ollama = _FakeContainer("cid-ollama", "atenea-ollama", "running")
    fc.containers._store["atenea-ollama"] = ollama

    return fc


FAKE_MODULE_SRC = """
class FakeDockerClient:
    pass
"""


def test_status_running(monkeypatch, fake_docker_client):
    """GET /api/docker/ollama/status returns running state."""
    import routes.docker_ollama as do
    monkeypatch.setattr(do, "_docker_client", lambda: fake_docker_client)
    router = do.setup_docker_ollama_routes()

    # Build a minimal FastAPI test request
    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.get("/api/docker/ollama/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert data["container_name"] == "atenea-ollama"
    assert data["running"] is True


def test_status_absent(monkeypatch, fake_docker_client):
    """Status reports absent when container does not exist."""
    import routes.docker_ollama as do
    # Clear the pre-created container
    fake_docker_client.containers._store.clear()
    monkeypatch.setattr(do, "_docker_client", lambda: fake_docker_client)

    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(do.setup_docker_ollama_routes())
    client = TestClient(app)

    resp = client.get("/api/docker/ollama/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "absent"


def test_start_creates_container(monkeypatch, fake_docker_client):
    """POST /api/docker/ollama/start creates + starts the container."""
    import routes.docker_ollama as do
    fake_docker_client.containers._store.clear()
    monkeypatch.setattr(do, "_docker_client", lambda: fake_docker_client)

    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(do.setup_docker_ollama_routes())
    client = TestClient(app)

    resp = client.post("/api/docker/ollama/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert data["container_name"] == "atenea-ollama"


def test_start_already_running(monkeypatch, fake_docker_client):
    """Starting an already-running container returns OK."""
    import routes.docker_ollama as do
    monkeypatch.setattr(do, "_docker_client", lambda: fake_docker_client)

    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(do.setup_docker_ollama_routes())
    client = TestClient(app)

    resp = client.post("/api/docker/ollama/start")
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_running"


def test_stop(monkeypatch, fake_docker_client):
    """POST /api/docker/ollama/stop stops a running container."""
    import routes.docker_ollama as do
    monkeypatch.setattr(do, "_docker_client", lambda: fake_docker_client)

    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(do.setup_docker_ollama_routes())
    client = TestClient(app)

    resp = client.post("/api/docker/ollama/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_stop_not_running(monkeypatch, fake_docker_client):
    """Stopping a container that doesn't exist reports not_running."""
    import routes.docker_ollama as do
    fake_docker_client.containers._store.clear()
    monkeypatch.setattr(do, "_docker_client", lambda: fake_docker_client)

    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(do.setup_docker_ollama_routes())
    client = TestClient(app)

    resp = client.post("/api/docker/ollama/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_running"


def test_docker_unavailable(monkeypatch):
    """When _docker_client returns None, status reports docker_unavailable."""
    import routes.docker_ollama as do
    monkeypatch.setattr(do, "_docker_client", lambda: None)

    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(do.setup_docker_ollama_routes())
    client = TestClient(app)

    resp = client.get("/api/docker/ollama/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "docker_unavailable"
