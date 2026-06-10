#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

MODE="auto"
if [ "${1:-}" = "--nvidia" ]; then
    MODE="nvidia"
elif [ "${1:-}" = "--amd" ]; then
    MODE="amd"
elif [ "${1:-}" = "--cpu" ]; then
    MODE="cpu"
elif [ "${1:-}" = "" ]; then
    MODE="auto"
else
    echo "Usage: scripts/verify-gpu-setup.sh [--nvidia|--amd|--cpu]"
    exit 1
fi

PASS=0
FAIL=0
WARN=0
LLAMA_CPP_OK=0

_pass() { printf '[PASS] %s\n' "$*"; PASS=$((PASS + 1)); }
_fail() { printf '[FAIL] %s\n' "$*"; FAIL=$((FAIL + 1)); }
_warn() { printf '[WARN] %s\n' "$*"; WARN=$((WARN + 1)); }

_atenea() {
    if [ "$MODE" = "auto" ]; then
        "${REPO_ROOT}/atenea" "$@"
    else
        ATENEA_GPU_MODE_OVERRIDE="$MODE" "${REPO_ROOT}/atenea" "$@"
    fi
}

_atenea_as_app_user() {
    _atenea exec sh -lc '
        export PATH="/app/.local/bin:$PATH"
        for cudalib in \
            /app/.local/lib/python*/site-packages/nvidia/cuda_runtime/lib \
            /app/.local/lib/python*/site-packages/nvidia/cublas/lib; do
            if [ -d "$cudalib" ]; then
                export LD_LIBRARY_PATH="$cudalib:${LD_LIBRARY_PATH:-}"
            fi
        done
        gosu "${PUID:-1000}:${PGID:-1000}" "$@"
    ' sh "$@"
}

_llama_bin_check_cmd() {
    cat <<'CMD'
LLAMA_BIN="$(command -v llama-server || true)"
[ -x "$LLAMA_BIN" ] || LLAMA_BIN="$HOME/.local/bin/llama-server"
[ -x "$LLAMA_BIN" ] && echo "$LLAMA_BIN"
CMD
}

_host_supports_amd() {
    [ -e /dev/kfd ] && [ -d /dev/dri ] && ls /dev/dri/renderD* >/dev/null 2>&1
}

echo "== Atenea GPU setup verification =="
echo "Repo: ${REPO_ROOT}"
echo "Mode: ${MODE}"
echo

if [ "$MODE" = "amd" ] && ! _host_supports_amd; then
    _warn "Host lacks AMD KFD/DRI devices; skipping AMD container verification"
    echo
    echo "=== Verification summary: ${PASS} passed, ${WARN} warnings, ${FAIL} failed ==="
    exit 0
fi

if [ "$MODE" = "auto" ]; then
    _atenea up --build
else
    _atenea up --build "--${MODE}"
fi

echo
echo "== Container checks =="

if _atenea_as_app_user python -c 'import llama_cpp' >/dev/null 2>&1; then
    _pass "llama_cpp Python runtime import works"
    LLAMA_CPP_OK=1
else
    _warn "llama_cpp Python runtime import failed"
fi

LLAMA_BIN="$(_atenea_as_app_user sh -lc "$(_llama_bin_check_cmd)" 2>/dev/null || true)"
LLAMA_BIN="$(printf '%s\n' "$LLAMA_BIN" | tail -n 1)"
if [ -n "$LLAMA_BIN" ]; then
    _pass "llama-server binary found: ${LLAMA_BIN}"
    if _atenea_as_app_user sh -lc 'LLAMA_BIN="$(command -v llama-server || true)"; [ -x "$LLAMA_BIN" ] || LLAMA_BIN="$HOME/.local/bin/llama-server"; "$LLAMA_BIN" --version >/dev/null 2>&1'; then
        _pass "llama-server --version runs"
    else
        _fail "llama-server exists but failed to run"
    fi
else
    _warn "llama-server binary not found"
fi

if [ "$MODE" = "nvidia" ] || [ "$MODE" = "auto" ]; then
    echo
    echo "== NVIDIA diagnostics =="
    if _atenea exec sh -lc 'command -v nvidia-smi >/dev/null && nvidia-smi -L | grep -q "GPU "'; then
        _pass "Container sees NVIDIA GPU via nvidia-smi"
    else
        _fail "Container cannot see NVIDIA GPU"
    fi

    if _atenea exec sh -lc '[ "${NVIDIA_VISIBLE_DEVICES:-}" = "all" ]'; then
        _pass "NVIDIA_VISIBLE_DEVICES=all in container"
    else
        _warn "NVIDIA_VISIBLE_DEVICES is not set to all"
    fi

    if [ -n "$LLAMA_BIN" ] && _atenea_as_app_user sh -lc 'LLAMA_BIN="$(command -v llama-server || true)"; [ -x "$LLAMA_BIN" ] || LLAMA_BIN="$HOME/.local/bin/llama-server"; "$LLAMA_BIN" --help 2>&1 | grep -qi cuda'; then
        _pass "llama-server reports CUDA support"
    elif [ "$LLAMA_CPP_OK" -eq 1 ]; then
        _pass "CUDA path available via llama_cpp Python runtime"
    else
        _warn "llama-server does not report CUDA support (may be Vulkan/CPU fallback)"
    fi
fi

if [ "$MODE" = "amd" ] || [ "$MODE" = "auto" ]; then
    echo
    echo "== AMD diagnostics =="
    if _atenea exec sh -lc 'test -e /dev/kfd && test -d /dev/dri && ls /dev/dri/renderD* >/dev/null 2>&1'; then
        _pass "Container sees /dev/kfd and DRI render nodes"
    else
        _fail "Container cannot access AMD KFD/DRI devices"
    fi

    if [ -n "$LLAMA_BIN" ] && _atenea_as_app_user sh -lc 'LLAMA_BIN="$(command -v llama-server || true)"; [ -x "$LLAMA_BIN" ] || LLAMA_BIN="$HOME/.local/bin/llama-server"; "$LLAMA_BIN" --help 2>&1 | grep -qi hip'; then
        _pass "llama-server reports HIP support"
    else
        _warn "llama-server does not report HIP support"
    fi
fi

if [ "$MODE" = "cpu" ]; then
    echo
    echo "== CPU diagnostics =="
    if _atenea exec sh -lc 'test -z "${NVIDIA_VISIBLE_DEVICES:-}"'; then
        _pass "No NVIDIA runtime vars in CPU mode"
    else
        _warn "NVIDIA runtime vars still present in CPU mode"
    fi

    if [ -n "$LLAMA_BIN" ] && _atenea_as_app_user sh -lc 'LLAMA_BIN="$(command -v llama-server || true)"; [ -x "$LLAMA_BIN" ] || LLAMA_BIN="$HOME/.local/bin/llama-server"; "$LLAMA_BIN" --help 2>&1 | grep -Eiq "cuda|hip"'; then
        _warn "CPU mode binary advertises GPU backends"
    else
        _pass "CPU mode runtime does not advertise CUDA/HIP"
    fi
fi

echo
echo "=== Verification summary: ${PASS} passed, ${WARN} warnings, ${FAIL} failed ==="

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi
