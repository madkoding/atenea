#!/usr/bin/env python3
"""Disable stale duplicate local model endpoints.

Usage:
  .venv/bin/python scripts/cleanup_stale_model_endpoints.py [--apply]

Without --apply it only prints what would change.
"""

from __future__ import annotations

import argparse
import json
import socket
from urllib.parse import urlparse

from core.database import SessionLocal, ModelEndpoint


def _is_reachable(base_url: str, timeout: float = 0.8) -> bool:
    try:
        parsed = urlparse(base_url or "")
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            return False
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _canon(base_url: str) -> str:
    try:
        parsed = urlparse((base_url or "").strip())
        path = (parsed.path or "").rstrip("/")
        if path.endswith("/v1"):
            path = path[:-3]
        host = (parsed.hostname or "").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return f"{host}:{port}{path}"
    except Exception:
        return (base_url or "").strip().lower().rstrip("/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="apply changes (otherwise dry-run)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()  # noqa: E712
        groups: dict[str, list[ModelEndpoint]] = {}
        for ep in rows:
            key = _canon(ep.base_url or "")
            groups.setdefault(key, []).append(ep)

        actions: list[dict] = []
        for key, eps in groups.items():
            if len(eps) < 2:
                continue
            scored = []
            for ep in eps:
                reachable = _is_reachable(ep.base_url or "")
                has_cache = bool((ep.cached_models or "").strip())
                owner_scoped = bool((ep.owner or "").strip())
                score = 0
                score += 10 if reachable else 0
                score += 3 if has_cache else 0
                score += 1 if owner_scoped else 0
                scored.append((score, ep, reachable, has_cache, owner_scoped))
            scored.sort(key=lambda x: (x[0], str(x[1].updated_at or ""), str(x[1].created_at or "")), reverse=True)
            keep = scored[0][1]
            for _, ep, reachable, has_cache, owner_scoped in scored[1:]:
                actions.append(
                    {
                        "key": key,
                        "keep_id": keep.id,
                        "disable_id": ep.id,
                        "disable_name": ep.name,
                        "disable_base": ep.base_url,
                        "reachable": reachable,
                        "has_cache": has_cache,
                        "owner_scoped": owner_scoped,
                    }
                )

        print(json.dumps({"dry_run": not args.apply, "actions": actions}, ensure_ascii=True, indent=2, default=str))

        if args.apply and actions:
            disable_ids = {a["disable_id"] for a in actions}
            for ep in rows:
                if ep.id in disable_ids:
                    ep.is_enabled = False
            db.commit()
            print(f"Applied: disabled {len(disable_ids)} stale duplicate endpoint(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
