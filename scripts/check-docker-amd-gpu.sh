#!/usr/bin/env bash
# check-docker-amd-gpu.sh — Diagnostic and optional .env setup helper for AMD/ROCm Docker GPU access.
#
# Default mode is READ-ONLY — does not install packages, modify config, or restart Docker.
# The Atenea app never calls this script automatically.
#
# USAGE
#   scripts/check-docker-amd-gpu.sh                             # read-only diagnostics (default)
#   scripts/check-docker-amd-gpu.sh --enable-amd-overlay        # also write COMPOSE_FILE + RENDER_GID to .env
#   scripts/check-docker-amd-gpu.sh --help

set -u

MODE="check"
OPT_YES=0
OPT_ENABLE_OVERLAY=0

PASS=0
FAIL=0
WARN=0
RENDER_GID=""
VIDEO_GID=""
TEST_IMAGE="${ATENEA_AMD_TEST_IMAGE:-alpine:3.20}"
_AMD_PASSTHROUGH_OK=0

_pass() { printf '\033[32m[PASS]\033[0m %s\n' "$*"; PASS=$((PASS + 1)); }
_fail() { printf '\033[31m[FAIL]\033[0m %s\n' "$*"; FAIL=$((FAIL + 1)); }
_warn() { printf '\033[33m[WARN]\033[0m %s\n' "$*"; WARN=$((WARN + 1)); }
_info() { printf '\033[34m[INFO]\033[0m %s\n' "$*"; }

_confirm() {
    printf '%s [y/N] ' "$1"
    read -r _ans
    case "${_ans}" in
        [Yy]|[Yy][Ee][Ss]) return 0 ;;
        *) return 1 ;;
    esac
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

_usage() {
    cat <<'USAGE'
Usage: scripts/check-docker-amd-gpu.sh [OPTIONS]

Read-only diagnostic (default — safe to run at any time, installs nothing):
  (no flags)                    Check host /dev/kfd, /dev/dri, render group, and
                                Docker AMD device passthrough.

Opt-in .env update (requires .env or .env.example in the repo root):
  --enable-amd-overlay          Write COMPOSE_FILE=docker-compose.yml:docker/gpu.amd.yml
                                and RENDER_GID=<detected> into .env. Creates a
                                timestamped backup first. Blocked if passthrough
                                is not working.
  --yes                         Skip confirmation prompts.
  --help                        Show this help.

Examples:
  scripts/check-docker-amd-gpu.sh
  scripts/check-docker-amd-gpu.sh --enable-amd-overlay
  scripts/check-docker-amd-gpu.sh --enable-amd-overlay --yes
USAGE
}

for _arg in "$@"; do
    case "${_arg}" in
        --help|-h)
            _usage
            exit 0
            ;;
        --enable-amd-overlay)
            OPT_ENABLE_OVERLAY=1
            ;;
        --yes|-y)
            OPT_YES=1
            ;;
        *)
            printf 'Unknown option: %s\n\n' "${_arg}" >&2
            _usage >&2
            exit 1
            ;;
    esac
done

_find_cmd() {
    if command -v "$1" >/dev/null 2>&1; then
        command -v "$1"
        return 0
    fi
    if [ -x "/opt/rocm/bin/$1" ]; then
        printf '/opt/rocm/bin/%s\n' "$1"
        return 0
    fi
    return 1
}

_check_host_devices() {
    _info "Checking host AMD device nodes..."
    if [ -e /dev/kfd ]; then
        _pass "/dev/kfd exists"
    else
        _fail "/dev/kfd is missing — ROCm kernel driver access is not available."
    fi

    if [ -d /dev/dri ]; then
        _pass "/dev/dri exists"
    else
        _fail "/dev/dri is missing — render devices are not available."
        return
    fi

    render_nodes="$(find /dev/dri -maxdepth 1 -type c -name 'renderD*' -print 2>/dev/null | sort)"
    if [ -n "${render_nodes}" ]; then
        _pass "Render nodes found:"
        printf '%s\n' "${render_nodes}" | sed 's/^/        /'
    else
        _fail "No /dev/dri/renderD* node found."
    fi
    echo
}

_check_groups() {
    _info "Checking host render/video groups..."
    RENDER_GID="$(getent group render | awk -F: '{print $3; exit}')"
    VIDEO_GID="$(getent group video | awk -F: '{print $3; exit}')"

    if [ -n "${RENDER_GID}" ]; then
        _pass "render group GID: ${RENDER_GID}"
    else
        _fail "render group not found — set RENDER_GID manually if your distro uses a different group."
    fi

    if [ -n "${VIDEO_GID}" ]; then
        _pass "video group GID: ${VIDEO_GID}"
    else
        _warn "video group not found. /dev/kfd and renderD* may still be enough on some hosts."
    fi
    echo
}

_check_host_rocm() {
    _info "Checking host ROCm tools..."
    rocminfo_cmd="$(_find_cmd rocminfo || true)"
    if [ -n "${rocminfo_cmd}" ]; then
        if "${rocminfo_cmd}" 2>/dev/null | grep -Eq 'gfx[0-9a-f]+'; then
            _pass "rocminfo works on the host: ${rocminfo_cmd}"
            "${rocminfo_cmd}" 2>/dev/null \
                | grep -E 'Marketing Name:|Name:[[:space:]]+gfx' \
                | head -12 \
                | sed 's/^/        /'
        else
            _warn "rocminfo exists but did not list a gfx target."
        fi
    else
        _warn "rocminfo not found on PATH or /opt/rocm/bin. This does not block Docker passthrough, but host ROCm may be incomplete."
    fi
    echo
}

_check_docker() {
    _info "Checking Docker..."
    if ! command -v docker >/dev/null 2>&1; then
        _fail "docker not found — install Docker first."
        echo
        return 1
    fi
    if docker info >/dev/null 2>&1; then
        _pass "Docker daemon is running."
    else
        _fail "Docker daemon is not running or this user lacks Docker permission."
        echo
        return 1
    fi
    echo
}

_check_docker_passthrough() {
    if [ -z "${RENDER_GID}" ]; then
        _fail "Skipping Docker passthrough smoke because render GID is unknown."
        echo
        return
    fi

    _info "Testing AMD device passthrough with ${TEST_IMAGE} (may pull on first run)..."
    group_args=(--group-add "${RENDER_GID}")
    if [ -n "${VIDEO_GID}" ]; then
        group_args+=(--group-add "${VIDEO_GID}")
    fi

    if docker run --rm \
        --device=/dev/kfd \
        --device=/dev/dri \
        "${group_args[@]}" \
        "${TEST_IMAGE}" \
        sh -lc 'test -e /dev/kfd && test -d /dev/dri && ls /dev/dri/renderD* >/dev/null' \
        >/dev/null 2>&1; then
        _AMD_PASSTHROUGH_OK=1
        _pass "Docker can pass /dev/kfd and /dev/dri render nodes into a container."
    else
        _fail "Docker AMD device passthrough failed."
        _info "Check that Docker can access /dev/kfd and /dev/dri, then retry."
    fi
    echo
}

# ─── --enable-amd-overlay ─────────────────────────────────────────────────────

_enable_amd_overlay() {
    echo "=== Enabling AMD compose overlay ==="
    echo

    local _env_file="${REPO_ROOT}/.env"
    local _env_example="${REPO_ROOT}/.env.example"
    local _overlay_fragment="docker/gpu.amd.yml"
    local _backup_ts
    _backup_ts="$(date +%Y%m%d-%H%M%S)"

    # Ensure .env exists
    if [ ! -f "${_env_file}" ]; then
        if [ -f "${_env_example}" ]; then
            _info ".env not found. .env.example is available."
            local _do_copy=0
            if [ "${OPT_YES}" -eq 1 ]; then
                _do_copy=1
            elif _confirm "Copy .env.example to .env?"; then
                _do_copy=1
            fi
            if [ "${_do_copy}" -eq 1 ]; then
                if ! cp "${_env_example}" "${_env_file}"; then
                    _fail "Failed to copy .env.example to .env."
                    return 1
                fi
                _pass "Copied .env.example to .env."
            else
                _fail ".env is required to set COMPOSE_FILE — aborted."
                return 1
            fi
        else
            _fail ".env not found and .env.example is missing."
            _info "Create a .env file in the repo root, then re-run."
            return 1
        fi
    fi

    # Back up .env before any edit
    local _backup="${_env_file}.bak.${_backup_ts}"
    if ! cp "${_env_file}" "${_backup}"; then
        _fail "Failed to create backup of .env — aborting to avoid data loss."
        return 1
    fi
    _info "Backup created: .env.bak.${_backup_ts}"

    # Read current active (uncommented) COMPOSE_FILE
    local _current_cf
    _current_cf="$(grep '^COMPOSE_FILE=' "${_env_file}" | tail -1 | cut -d= -f2-)"

    # Idempotency check
    local _already=0
    if echo "${_current_cf}" | grep -qF "${_overlay_fragment}"; then
        _pass "COMPOSE_FILE already includes the AMD overlay."
        _already=1
    fi

    if [ "${_already}" -eq 0 ]; then
        local _new_cf=""
        if [ -z "${_current_cf}" ]; then
            _new_cf="docker-compose.yml:${_overlay_fragment}"
            if ! printf '\nCOMPOSE_FILE=%s\n' "${_new_cf}" >> "${_env_file}"; then
                _fail "Failed to write COMPOSE_FILE to .env."
                return 1
            fi
        else
            _new_cf="${_current_cf}:${_overlay_fragment}"
            local _tmp="${_env_file}.tmp"
            if ! sed "s|^COMPOSE_FILE=.*|COMPOSE_FILE=${_new_cf}|" "${_env_file}" > "${_tmp}"; then
                _fail "Failed to update COMPOSE_FILE in .env."
                rm -f "${_tmp}"
                return 1
            fi
            if ! mv "${_tmp}" "${_env_file}"; then
                _fail "Failed to write updated .env."
                rm -f "${_tmp}"
                return 1
            fi
        fi
        _pass "COMPOSE_FILE set to: ${_new_cf}"
    fi

    # Write RENDER_GID if detected
    if [ -n "${RENDER_GID}" ]; then
        local _current_rg
        _current_rg="$(grep '^RENDER_GID=' "${_env_file}" | tail -1 | cut -d= -f2-)"
        if [ "${_current_rg}" = "${RENDER_GID}" ]; then
            _pass "RENDER_GID already set to ${RENDER_GID}."
        else
            # Remove any existing RENDER_GID line
            local _tmp2="${_env_file}.tmp2"
            grep -v '^RENDER_GID=' "${_env_file}" > "${_tmp2}" || true
            printf 'RENDER_GID=%s\n' "${RENDER_GID}" >> "${_tmp2}"
            mv "${_tmp2}" "${_env_file}"
            _pass "RENDER_GID set to: ${RENDER_GID}"
        fi
    else
        _warn "RENDER_GID not detected — you must set it manually in .env."
    fi

    echo
    _info "Build and start Atenea with AMD GPU support:"
    _info "  docker compose build --build-arg AMDGPU_TARGETS=gfx1030"
    _info "  docker compose up -d"
    echo
    _info "To undo, restore the backup:"
    _info "  cp ${_backup} ${_env_file}"
}

# ─── main ─────────────────────────────────────────────────────────────────────

echo "=== Atenea AMD Docker GPU diagnostic ==="
echo
_check_host_devices
_check_groups
_check_host_rocm
if _check_docker; then
    _check_docker_passthrough
fi

if [ "${OPT_ENABLE_OVERLAY}" -eq 1 ]; then
    if [ "${_AMD_PASSTHROUGH_OK}" -eq 0 ]; then
        _fail "AMD GPU passthrough is not working — .env will not be modified."
        _info "Fix passthrough first, then re-run with --enable-amd-overlay."
        echo
    else
        _enable_amd_overlay
    fi
fi

echo "=== Results: ${PASS} passed, ${WARN} warnings, ${FAIL} failed ==="
[ "${FAIL}" -eq 0 ]
