#!/usr/bin/env python3
"""Repair sessions that point to stale/unreachable model endpoints.

Usage:
  .venv/bin/python scripts/repair_stale_session_endpoints.py [--apply] [--clear-unrepairable]

Dry-run by default (prints proposed changes only).
"""

from __future__ import annotations

import argparse
import json
import socket
from urllib.parse import urlparse

from core.database import SessionLocal, ModelEndpoint, Session as DBSession
from src.runtime.endpoint_resolver import build_chat_url, normalize_base


def _host_port_reachable(url: str, timeout: float = 0.8) -> bool:
    try:
        parsed = urlparse((url or "").strip())
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            return False
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _parse_models(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            out = []
            for item in val:
                m = str(item or "").strip()
                if m:
                    out.append(m)
            return out
    except Exception:
        pass
    return []


def _chat_variants(url: str) -> set[str]:
    u = (url or "").strip().rstrip("/")
    if not u:
        return set()
    base = normalize_base(u).rstrip("/")
    return {u, base, base + "/chat/completions", build_chat_url(base).rstrip("/")}


def _best_replacement(
    sess: DBSession,
    endpoints: list[ModelEndpoint],
    default_endpoint_id: str,
    default_model: str,
) -> tuple[str, str] | None:
    current_model = (sess.model or "").strip()
    current_url = (sess.endpoint_url or "").strip()

    reachable_eps: list[tuple[ModelEndpoint, str, list[str]]] = []
    for ep in endpoints:
        base = normalize_base(ep.base_url or "")
        chat_url = build_chat_url(base)
        if _host_port_reachable(chat_url):
            reachable_eps.append((ep, chat_url, _parse_models(ep.cached_models)))

    if not reachable_eps:
        return None

    current_variants = _chat_variants(current_url)

    # 1) Keep same model on a reachable endpoint if possible.
    if current_model:
        for ep, chat_url, models in reachable_eps:
            if chat_url.rstrip("/") in current_variants:
                continue
            if current_model in models:
                return chat_url, current_model

    # 2) Respect default endpoint/model if reachable.
    if default_endpoint_id:
        for ep, chat_url, models in reachable_eps:
            if ep.id != default_endpoint_id:
                continue
            if default_model and default_model in models:
                return chat_url, default_model
            if models:
                return chat_url, models[0]

    # 3) Fallback to any reachable endpoint with same model.
    if current_model:
        for _ep, chat_url, models in reachable_eps:
            if current_model in models:
                return chat_url, current_model

    # 4) Fallback to first model in first reachable endpoint.
    for _ep, chat_url, models in reachable_eps:
        if models:
            return chat_url, models[0]

    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="apply session updates")
    parser.add_argument(
        "--clear-unrepairable",
        action="store_true",
        help="when --apply is set, clear session endpoint/model if no reachable replacement exists",
    )
    args = parser.parse_args()

    # Settings live in JSON (global defaults).
    try:
        with open("data/settings.json", encoding="utf-8") as fh:
            settings = json.load(fh)
    except Exception:
        settings = {}
    default_endpoint_id = str(settings.get("default_endpoint_id") or "").strip()
    default_model = str(settings.get("default_model") or "").strip()

    db = SessionLocal()
    try:
        endpoints = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()  # noqa: E712
        sessions = db.query(DBSession).all()

        actions = []
        unresolved = []
        updates = []
        for sess in sessions:
            current_url = (sess.endpoint_url or "").strip()
            if not current_url:
                continue
            if _host_port_reachable(current_url):
                continue

            repl = _best_replacement(sess, endpoints, default_endpoint_id, default_model)
            if not repl:
                unresolved.append(
                    {
                        "session_id": sess.id,
                        "url": current_url,
                        "model": sess.model or "",
                    }
                )
                if args.apply and args.clear_unrepairable:
                    updates.append((sess, "", ""))
                continue
            new_url, new_model = repl
            if new_url == current_url and new_model == (sess.model or ""):
                continue
            actions.append(
                {
                    "session_id": sess.id,
                    "from_url": current_url,
                    "from_model": sess.model or "",
                    "to_url": new_url,
                    "to_model": new_model,
                }
            )
            updates.append((sess, new_url, new_model))

        print(
            json.dumps(
                {
                    "dry_run": not args.apply,
                    "actions": actions,
                    "unresolved": unresolved,
                    "clear_unrepairable": bool(args.clear_unrepairable),
                },
                ensure_ascii=True,
                indent=2,
            )
        )

        if args.apply and updates:
            for sess, new_url, new_model in updates:
                sess.endpoint_url = new_url
                sess.model = new_model
            db.commit()
            print(f"Applied: repaired {len(updates)} session(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
