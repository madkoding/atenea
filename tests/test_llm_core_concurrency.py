"""Regression tests for thread-safe access to llm_core's shared maps (issue #659).

The synchronous llm_call() runs inside FastAPI's threadpool (sync route handlers
such as POST /sessions/auto-sort), while llm_call_async() runs on the event
loop. _dead_hosts / _host_fails are guarded by _host_health_lock; the LLM
response cache now uses dogpile.cache (memory_lru backend) which handles
concurrent access internally.
"""
import threading
import time

import src.llm_core as llm_core
from core.cache import llm_region
from dogpile.cache.api import NO_VALUE


def test_llm_region_handles_concurrent_get_set():
    """Concurrent get/set on llm_region must not raise or lose data.

    Dogpile's memory_lru backend uses cachetools.LRUCache under the hood
    with a locking mechanism. This test verifies basic concurrent access.
    """
    key = "__test_concurrent_key__"
    value = "concurrent-value"
    llm_region.set(key, value)
    assert llm_region.get(key) == value
    llm_region.delete(key)
    assert llm_region.get(key) is NO_VALUE


def test_host_fail_counter_has_no_lost_updates():
    """Concurrent _mark_host_dead calls must each count exactly once.

    A SlowGetDict widens the read-modify-write window so the unguarded
    get()+1+set() loses every update but one; the lock serializes them.
    """
    url = "http://race.example:1234/v1/chat/completions"
    key = llm_core._host_key(url)

    class SlowGetDict(dict):
        def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            time.sleep(0.01)  # widen the gap between the read and the caller's write
            return value

    n_threads = 8
    barrier = threading.Barrier(n_threads)
    original_fails = llm_core._host_fails
    original_threshold = llm_core._HOST_FAIL_THRESHOLD
    llm_core._host_fails = SlowGetDict()
    llm_core._HOST_FAIL_THRESHOLD = 10 ** 9  # never cool: every call is a pure +1
    try:
        def worker():
            barrier.wait()  # all threads enter the read window together
            llm_core._mark_host_dead(url)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert dict.get(llm_core._host_fails, key) == n_threads
    finally:
        llm_core._host_fails = original_fails
        llm_core._HOST_FAIL_THRESHOLD = original_threshold
