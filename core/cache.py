# core/cache.py
"""Cache regions for database queries, LLM responses, settings, and context.

Usage:
    from core.cache import db_region, llm_region
    from dogpile.cache.api import NO_VALUE

    # Decorator (sync functions only)
    @db_region.cache_on_arguments(namespace="sessions")
    def get_active_sessions():
        ...

    # Manual get/set (async or custom logic)
    cached = llm_region.get(key)
    if cached is not NO_VALUE:
        return cached
    result = await fetch()
    llm_region.set(key, result)
    return result
"""

import os
from dogpile.cache import make_region


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


# DB query results cache (session list, session detail, etc.)
# TTL-based eviction prevents unbounded growth.
db_region = make_region().configure(
    "dogpile.cache.memory",
    expiration_time=_env_int("CACHE_DB_TTL", 300),
)

# LLM response exact-match cache (identical prompts -> cached response)
# 24h TTL; typical usage is well under 128 entries (~a few MB).
llm_region = make_region().configure(
    "dogpile.cache.memory",
    expiration_time=_env_int("CACHE_LLM_TTL", 86400),
)

# Settings/features cache -- very short TTL (2s), matches current hot-path cache
settings_region = make_region().configure(
    "dogpile.cache.memory",
    expiration_time=_env_int("CACHE_SETTINGS_TTL", 2),
)

# Context window cache per (endpoint_url, model)
context_region = make_region().configure(
    "dogpile.cache.memory",
    expiration_time=_env_int("CACHE_CONTEXT_TTL", 3600),
)


def invalidate_all():
    """Invalidate every cache region. Used in tests and admin resets."""
    db_region.invalidate()
    llm_region.invalidate()
    settings_region.invalidate()
    context_region.invalidate()
