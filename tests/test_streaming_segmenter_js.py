"""Runs the Node-based streaming-render segmenter suite (tests/streaming/*.test.mjs).

Covers the pure incremental-render segmenter (static/js/streamingSegmenter.js):
unit boundaries plus a streaming-invariant fuzz that feeds a markdown corpus in
token-by-token and asserts the freeze/tail split always matches a single full
render. Pure JS — no DOM, no extra dependencies. Skipped when node is
unavailable, mirroring tests/test_markdown_rendering_js.py.

The renderer's DOM behavior (streamingRenderer.js) is exercised against a running
app, not here, consistent with how this project tests browser-coupled code.
"""

import shutil
import subprocess
import os
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_HAS_NODE = shutil.which("node") is not None


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_streaming_segmenter_suite():
    test_files = sorted(str(p) for p in (_REPO / "tests" / "streaming").glob("*.test.mjs"))
    assert test_files, "no streaming test files found"

    for test_file in test_files:
        env = dict(os.environ)
        node_opts = env.get("NODE_OPTIONS", "").strip()
        env["NODE_OPTIONS"] = (node_opts + " --jitless").strip() if node_opts else "--jitless"
        result = subprocess.run(
            ["node", "--test", "--test-concurrency=1", test_file],
            cwd=_REPO,
            env=env,
            capture_output=True,
            timeout=180,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"node --test failed for {test_file}:\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
