import os
import sys
import json
from datetime import datetime
from unittest.mock import patch

import pytest

from tests.helpers.import_state import clear_module, preserve_import_state


def _import_webhook_manager():
    """Import webhook_manager with a clean in-memory DB to avoid init_db I/O."""
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}), \
            preserve_import_state("src.database", "core.database", "src.clients.webhook_manager"):
        clear_module("src.database")
        for _mod_name in ("src.clients.webhook_manager",):
            sys.modules.pop(_mod_name, None)
            _pkg_name, _, _attr = _mod_name.rpartition(".")
            _pkg = sys.modules.get(_pkg_name)
            if _pkg is not None and hasattr(_pkg, _attr):
                delattr(_pkg, _attr)
        _core_database = sys.modules.get("core.database")
        _core_database_all = (
            getattr(_core_database, "__all__", None) if _core_database is not None else None
        )
        if _core_database is not None and (
            not getattr(_core_database, "__file__", None)
            or (
                _core_database_all is not None
                and (
                    not isinstance(_core_database_all, (list, tuple, set))
                    or not all(isinstance(name, str) for name in _core_database_all)
                )
            )
        ):
            del sys.modules["core.database"]
        import src.clients.webhook_manager as wm
        return wm


def test_webhook_url_ssrf_mitigation():
    wm = _import_webhook_manager()
    private_urls = [
        "http://[::]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",
        "http://127.0.0.1/",
        "http://0.0.0.0/",
    ]
    for url in private_urls:
        with pytest.raises(ValueError) as exc:
            wm.validate_webhook_url(url)
        assert "private/internal addresses" in str(exc.value)

    public_url = "http://93.184.216.34/"
    assert wm.validate_webhook_url(public_url) == public_url


@pytest.mark.asyncio
async def test_webhook_delivery_uses_naive_utc_timestamps(monkeypatch):
    wm = _import_webhook_manager()

    class _Query:
        def __init__(self, updates):
            self.updates = updates

        def filter(self, *_args, **_kwargs):
            return self

        def update(self, values):
            self.updates.append(values)

    class _Db:
        def __init__(self):
            self.updates = []
            self.committed = False
            self.closed = False

        def query(self, _model):
            return _Query(self.updates)

        def commit(self):
            self.committed = True

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    class _Response:
        status_code = 204

    class _Client:
        def __init__(self):
            self.content = ""

        async def post(self, _url, content, headers):
            self.content = content
            assert headers["X-Odysseus-Event"] == "webhook.test"
            return _Response()

    db = _Db()
    client = _Client()
    monkeypatch.setattr(wm, "SessionLocal", lambda: db)

    manager = wm.WebhookManager()
    await manager._client.aclose()
    manager._client = client

    await manager._deliver("hook-1", "http://93.184.216.34/", None, "webhook.test", {"ok": True})

    body = json.loads(client.content)
    payload_timestamp = datetime.fromisoformat(body["timestamp"])
    assert payload_timestamp.tzinfo is None
    assert db.updates[0]["last_triggered_at"].tzinfo is None
    assert db.updates[0]["last_status_code"] == 204
    assert db.committed is True
    assert db.closed is True
