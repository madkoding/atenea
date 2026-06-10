#!/usr/bin/env python3
"""Atenea — first-time setup script.

Creates data directories, initializes the database, and sets up an
initial admin user. Safe to re-run (skips what already exists).
"""

import os
import platform
import re
import shutil
import subprocess
import sys
import glob
import ctypes
import site
import importlib.util
import time
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

_IN_DOCKER = os.path.exists("/.dockerenv")
from src.constants import (
    DATA_DIR, AUTH_FILE, UPLOAD_DIR, PERSONAL_DIR, PERSONAL_UPLOADS_DIR,
    TTS_CACHE_DIR, GENERATED_IMAGES_DIR, DEEP_RESEARCH_DIR, CHROMA_DIR,
    RAG_DIR, MEMORY_VECTORS_DIR,
)

DIRS = [
    DATA_DIR,
    UPLOAD_DIR,
    PERSONAL_DIR,
    PERSONAL_UPLOADS_DIR,
    TTS_CACHE_DIR,
    GENERATED_IMAGES_DIR,
    DEEP_RESEARCH_DIR,
    CHROMA_DIR,
    RAG_DIR,
    MEMORY_VECTORS_DIR,
    os.path.join(BASE_DIR, "logs"),
]


def create_dirs():
    for d in DIRS:
        os.makedirs(d, exist_ok=True)
        print(f"  [ok] {os.path.relpath(d, BASE_DIR)}/")


def init_database():
    """Create all SQLAlchemy tables."""
    sys.path.insert(0, BASE_DIR)
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(DATA_DIR, 'app.db')}")

    from core.database import Base, engine
    Base.metadata.create_all(bind=engine)
    print("  [ok] Database initialized")


def _prompt_admin_credentials():
    """Interactively ask for admin username and password when running in a terminal."""
    import getpass

    print()
    print("  Set up your admin account:")
    print("  (Press Enter to accept defaults)")
    print()

    username = input("  Username [admin]: ").strip().lower()
    if not username:
        username = "admin"

    while True:
        password = getpass.getpass("  Password: ")
        if not password:
            print("  Password cannot be empty.")
            continue
        confirm = getpass.getpass("  Confirm password: ")
        if password != confirm:
            print("  Passwords don't match. Try again.")
            continue
        break

    return username, password


def create_default_admin():
    """Create an initial admin user if none exists.

    Returns (status, username, password, show_password) where status is one of
    "exists", "created", "skipped", "failed".
    """
    auth_path = AUTH_FILE
    if os.path.exists(auth_path):
        print("  [skip] auth.json already exists")
        return "exists", "", "", False

    try:
        import bcrypt
        import json

        username = os.getenv("ATENEA_ADMIN_USER", "").strip().lower()
        password = os.getenv("ATENEA_ADMIN_PASSWORD", "").strip()
        show_password = False

        if username and password:
            show_password = False
        elif sys.stdin.isatty() and not os.getenv("ATENEA_SKIP_ADMIN_PROMPT"):
            username, password = _prompt_admin_credentials()
            show_password = False
        else:
            username = username or "admin"
            password = password or __import__("secrets").token_urlsafe(18)
            show_password = True

        username = username or "admin"
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        auth_data = {
            "users": {
                username: {
                    "password_hash": hashed,
                    "is_admin": True,
                }
            }
        }
        with open(auth_path, "w", encoding="utf-8") as f:
            json.dump(auth_data, f, indent=2)

        print(f"  [ok] Admin account created ({username})")
        return "created", username, password, show_password
    except ImportError as e:
        if "incompatible architecture" in str(e).lower():
            print("  [error] bcrypt loaded with the wrong CPU architecture.")
            print("          Rebuild the venv with an arm64 Python:")
            print("            rm -rf venv && /opt/homebrew/bin/python3.12 -m venv venv")
            print("            ./venv/bin/pip install -r requirements.txt")
            return "skipped", "", "", False
        print("  [warn] bcrypt not installed — skipping admin user creation")
        print("         Run: pip install bcrypt")
        return "skipped", "", "", False


def create_env():
    """Copy .env.example to .env if it doesn't exist."""
    env_path = os.path.join(BASE_DIR, ".env")
    example_path = os.path.join(BASE_DIR, ".env.example")
    if os.path.exists(env_path):
        print("  [skip] .env already exists")
        return
    if os.path.exists(example_path):
        import shutil
        shutil.copy2(example_path, env_path)
        print("  [ok] .env created from .env.example")
        print("        ** Edit .env with your LLM host and API keys **")
    else:
        print("  [warn] .env.example not found — create .env manually")


def _detect_gpu_backend() -> str:
    """Detect available GPU compute backend: cuda, rocm, vulkan, or cpu."""
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return "cuda"
    except: pass
    if os.path.isdir("/opt/rocm") or os.environ.get("ROCM_PATH") or os.environ.get("HIP_PATH"):
        return "rocm"
    try:
        r = subprocess.run(["hipconfig"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return "rocm"
    except: pass
    try:
        r = subprocess.run(["vulkaninfo"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return "vulkan"
    except: pass
    return "cpu"


def _has_llama_cpp_python() -> bool:
    _activate_cuda_runtime_libs()
    try:
        __import__("llama_cpp")
        return True
    except Exception:
        return False


def _site_packages_roots() -> list[str]:
    roots: list[str] = []
    roots.extend([p for p in site.getsitepackages() if isinstance(p, str)])
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass
    roots.extend([p for p in sys.path if isinstance(p, str) and "site-packages" in p])
    seen: set[str] = set()
    out: list[str] = []
    for path in roots:
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _nvidia_lib_dirs() -> list[str]:
    dirs: list[str] = []
    for root in _site_packages_roots():
        dirs.append(os.path.join(root, "nvidia", "cuda_runtime", "lib"))
        dirs.append(os.path.join(root, "nvidia", "cublas", "lib"))
    out: list[str] = []
    seen: set[str] = set()
    for path in dirs:
        if not os.path.isdir(path) or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _prepend_ld_library_path(paths: list[str]) -> None:
    if not paths:
        return
    current = os.environ.get("LD_LIBRARY_PATH", "")
    existing = [p for p in current.split(":") if p]
    merged = existing[:]
    for path in reversed(paths):
        if path not in merged:
            merged.insert(0, path)
    os.environ["LD_LIBRARY_PATH"] = ":".join(merged)


def _activate_cuda_runtime_libs() -> None:
    lib_dirs = _nvidia_lib_dirs()
    _prepend_ld_library_path(lib_dirs)
    for lib_dir in lib_dirs:
        for name in ("libcudart.so.12", "libcublas.so.12"):
            path = os.path.join(lib_dir, name)
            if not os.path.exists(path):
                continue
            try:
                ctypes.CDLL(path, mode=getattr(ctypes, "RTLD_GLOBAL", 0))
            except Exception:
                continue


def _llama_cpp_supports_gpu_offload() -> bool:
    """Best-effort True when installed llama-cpp-python is CUDA-capable."""
    try:
        _activate_cuda_runtime_libs()
        spec = importlib.util.find_spec("llama_cpp")
        if spec is None or not spec.origin:
            return False
        pkg_dir = os.path.dirname(spec.origin)
        lib_dir = os.path.join(pkg_dir, "lib")
        has_cuda_backend = bool(glob.glob(os.path.join(lib_dir, "libggml-cuda.so*")))
        if not has_cuda_backend:
            return False

        r = subprocess.run(
            [sys.executable, "-c", "import llama_cpp"],
            capture_output=True,
            text=True,
            timeout=15,
            env=os.environ.copy(),
        )
        return r.returncode == 0 and _has_visible_cudart()
    except Exception:
        return False


def _find_cudart_paths() -> list[str]:
    """Best-effort list of libcudart candidate paths."""
    candidates: list[str] = []
    for lib_dir in _nvidia_lib_dirs():
        candidates.extend(sorted(glob.glob(os.path.join(lib_dir, "libcudart.so*"))))
    candidates.extend(sorted(glob.glob(os.path.expanduser(
        "~/.local/lib/python*/site-packages/nvidia/cuda_runtime/lib/libcudart.so*"
    ))))
    candidates.extend(sorted(glob.glob("/usr/local/cuda/lib64/libcudart.so*")))
    candidates.extend(sorted(glob.glob("/usr/lib*/libcudart.so*")))
    seen: set[str] = set()
    out: list[str] = []
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _has_visible_cudart() -> bool:
    """Return True if libcudart can be loaded in the current process."""
    _activate_cuda_runtime_libs()
    try:
        ctypes.CDLL("libcudart.so", mode=getattr(ctypes, "RTLD_GLOBAL", 0))
        return True
    except Exception:
        pass
    for so in _find_cudart_paths():
        try:
            ctypes.CDLL(so, mode=getattr(ctypes, "RTLD_GLOBAL", 0))
            return True
        except Exception:
            continue
    return False


def _llama_server_supports_gpu_backend(path: str | None = None) -> bool:
    """Return True if llama-server advertises a GPU backend in --help."""
    exe = path or shutil.which("llama-server")
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=10)
    except Exception:
        return False
    text = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
    return bool(re.search(r"\b(cuda|hip|vulkan|metal|sycl)\b", text))


def _llama_server_supports_cuda_backend(path: str | None = None) -> bool:
    """Return True if llama-server specifically advertises CUDA support."""
    exe = path or shutil.which("llama-server")
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=10)
    except Exception:
        return False
    text = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
    return bool(re.search(r"\bcuda\b", text))


def _cuda_runtime_ready() -> bool:
    """True when a CUDA-capable llama runtime is actually available."""
    if _llama_server_supports_cuda_backend():
        return True
    return _has_llama_cpp_python() and _llama_cpp_supports_gpu_offload() and _has_visible_cudart()


def _pip_install(*args: str, user: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"]
    if user:
        cmd.append("--user")
    return subprocess.run(
        cmd + list(args),
        capture_output=True, text=True,
    )


def _pip_install_prebuilt(package: str, extra_index: str, force_reinstall: bool = False) -> bool:
    """Install a prebuilt wheel only; never fall back to source build."""
    args = [
        "--only-binary=:all:",
        package,
        "--extra-index-url",
        extra_index,
    ]
    if force_reinstall:
        args.extend(["--force-reinstall", "--no-cache-dir"])
    r = _pip_install(*args, user=_IN_DOCKER)
    if r.returncode != 0:
        return False
    return _has_llama_cpp_python()


def _download_release_asset(tag: str, asset_name: str, dest: str) -> str | None:
    """Download a GitHub release tarball and extract llama-server to dest. Returns the binary path."""
    import urllib.request, tarfile, io, tempfile
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{asset_name}"
    print(f"     Downloading {asset_name} ({tag})...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "atenea-setup"})
        data = urllib.request.urlopen(req, timeout=180).read()
        tmp = tempfile.mkdtemp()
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(tmp, filter="data")
        for root, _dirs, files in os.walk(tmp):
            if "llama-server" in files:
                src = os.path.join(root, "llama-server")
                dst = os.path.join(dest, "llama-server")
                shutil.move(src, dst)
                os.chmod(dst, 0o755)

                # Keep release-shipped shared libs next to the binary. Some
                # upstream builds resolve private libs from $ORIGIN.
                for name in files:
                    if name.startswith("lib") and ".so" in name:
                        lib_src = os.path.join(root, name)
                        lib_dst = os.path.join(dest, name)
                        if os.path.exists(lib_dst):
                            try:
                                os.remove(lib_dst)
                            except OSError:
                                pass
                        shutil.move(lib_src, lib_dst)

                shutil.rmtree(tmp, ignore_errors=True)
                return dst
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        print(f"     Download failed: {e}")
    return None


def _latest_llama_release_tag() -> str:
    """Fetch the latest llama.cpp release tag from GitHub."""
    import urllib.request, json
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest",
            headers={"Accept": "application/json", "User-Agent": "atenea-setup"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())["tag_name"]
    except Exception as e:
        print(f"  [warn] Could not fetch latest release: {e}")
        return "b9585"


def _recent_llama_release_tags(limit: int = 20) -> list[str]:
    """Fetch recent llama.cpp release tags (newest first)."""
    import urllib.request, json
    tags: list[str] = []
    page = 1
    while len(tags) < limit:
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30&page={page}",
                headers={"Accept": "application/json", "User-Agent": "atenea-setup"},
            )
            resp = urllib.request.urlopen(req, timeout=20)
            payload = json.loads(resp.read())
            if not payload:
                break
            for rel in payload:
                tag = rel.get("tag_name")
                if tag and tag not in tags:
                    tags.append(tag)
                    if len(tags) >= limit:
                        break
            page += 1
        except Exception:
            break
    return tags


def _asset_exists(tag: str, asset_name: str) -> bool:
    """Check if a release asset exists without downloading it."""
    import urllib.request

    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{asset_name}"
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "atenea-setup"})
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception:
        return False


def _ensure_cuda_wheel():
    """Install the prebuilt CUDA llama-cpp-python wheel (no source build)."""
    marker = os.path.join(DATA_DIR, ".cuda-wheel-installed")
    if os.path.exists(marker):
        if _has_llama_cpp_python() and _llama_cpp_supports_gpu_offload():
            return True
        try:
            os.remove(marker)
        except OSError:
            pass
    # Runtime deps required by CUDA wheels on slim images.
    _pip_install("nvidia-cuda-runtime-cu12", user=_IN_DOCKER)
    _pip_install("nvidia-cublas-cu12", user=_IN_DOCKER)
    print("  [info] Installing CUDA wheel for llama-cpp-python...")
    if _pip_install_prebuilt(
        "llama-cpp-python[server]",
        "https://abetlen.github.io/llama-cpp-python/whl/cu124",
        force_reinstall=True,
    ) and _llama_cpp_supports_gpu_offload():
        open(marker, "w").close()
        print("  [ok] llama-cpp-python with CUDA installed")
        return True
    if _has_llama_cpp_python() and not _llama_cpp_supports_gpu_offload():
        print("  [warn] llama-cpp-python is installed but GPU offload is not available (CPU-only runtime)")
    print("  [warn] CUDA wheel not available for this Python version")
    return False


def _ensure_cpu_wheel():
    """Install the prebuilt CPU llama-cpp-python wheel (no source build)."""
    marker = os.path.join(DATA_DIR, ".cpu-wheel-installed")
    if os.path.exists(marker):
        if _has_llama_cpp_python():
            return True
        try:
            os.remove(marker)
        except OSError:
            pass
    print("  [info] Installing CPU wheel for llama-cpp-python...")
    if _pip_install_prebuilt(
        "llama-cpp-python[server]",
        "https://abetlen.github.io/llama-cpp-python/whl/cpu",
    ):
        open(marker, "w").close()
        print("  [ok] llama-cpp-python CPU wheel installed")
        return True
    print("  [warn] CPU wheel installation failed")
    return False


def setup_llamacpp() -> bool:
    """Auto-detect hardware and install prebuilt llama.cpp binaries/wheels.

    Returns True when a usable runtime was installed/detected. On CUDA hosts,
    True means CUDA-capable runtime (not CPU-only fallback).
    """
    existing = shutil.which("llama-server")
    backend = _detect_gpu_backend()
    while existing:
        try:
            r = subprocess.run([existing, "--version"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                if backend == "cuda" and not _llama_server_supports_gpu_backend(existing):
                    print("  [warn] llama-server is installed but appears CPU-only on a CUDA host; replacing it")
                    try:
                        os.remove(existing)
                    except OSError:
                        pass
                    existing = shutil.which("llama-server")
                    continue
                print("  [ok] llama-server already installed")
                if _IN_DOCKER and backend == "cuda":
                    if not _has_visible_cudart():
                        print("  [warn] libcudart not visible; installing CUDA runtime Python packages")
                    _ensure_cuda_wheel()
                if backend != "cuda":
                    return True
                if _cuda_runtime_ready():
                    return True
                print("  [warn] CUDA host detected but active llama runtime is still CPU-only")
                return False
        except: pass
        print(f"  [warn] Removing broken llama-server at {existing}")
        os.remove(existing)
        existing = shutil.which("llama-server")

    try:
        __import__("llama_cpp")
        print("  [ok] llama-cpp-python already installed")
        if backend == "cuda":
            if not _has_visible_cudart():
                print("  [warn] libcudart not visible; installing CUDA runtime Python packages")
            _ensure_cuda_wheel()
            if _cuda_runtime_ready():
                return True
            print("  [warn] CUDA host detected but llama-cpp runtime remains CPU-only")
            return False
        return True
    except (ImportError, RuntimeError) as e:
        if isinstance(e, RuntimeError):
            print(f"  [warn] llama-cpp-python is installed but broken: {e}")

    machine = platform.machine()
    system = platform.system().lower()
    install_dir = os.path.expanduser("~/.local/bin")
    os.makedirs(install_dir, exist_ok=True)

    if system == "darwin":
        if shutil.which("brew"):
            print("  Installing llama-server via Homebrew...")
            r = subprocess.run(["brew", "install", "llama.cpp"], capture_output=True, text=True)
            if r.returncode == 0:
                print("  [ok] llama-server installed via Homebrew")
                return
        arch = "arm64" if machine == "arm64" else "x64"
        tag = _latest_llama_release_tag()
        asset = f"llama-{tag}-bin-macos-{arch}.tar.gz"
        print(f"  Downloading pre-built llama-server ({tag})...")
        if _download_release_asset(tag, asset, install_dir):
            print(f"  [ok] llama-server installed in {install_dir}")
            return
    else:
        tag = _latest_llama_release_tag()
        if backend == "cuda":
            # Linux CUDA prebuilt tarballs are not always published. Prefer
            # official prebuilt Python CUDA wheels (no source compile).
            if _ensure_cuda_wheel():
                return True
            print("  [warn] CUDA wheel unavailable; probing release assets across recent tags...")
            recent_tags = _recent_llama_release_tags(limit=25)
            if not recent_tags:
                recent_tags = [tag]
            elif tag in recent_tags:
                recent_tags = [tag] + [t for t in recent_tags if t != tag]
            else:
                recent_tags = [tag] + recent_tags

            cuda_assets = (
                ("llama-{tag}-bin-ubuntu-cuda-12.4-x64.tar.gz", "CUDA 12.4"),
                ("llama-{tag}-bin-ubuntu-cuda-13.3-x64.tar.gz", "CUDA 13.3"),
            )
            installed_cuda = False
            for probe_tag in recent_tags:
                for asset_tpl, label in cuda_assets:
                    asset = asset_tpl.format(tag=probe_tag)
                    if not _asset_exists(probe_tag, asset):
                        continue
                    print(f"  Downloading pre-built llama-server ({label}, {probe_tag})...")
                    dst = _download_release_asset(probe_tag, asset, install_dir)
                    if dst:
                        print(f"  [ok] llama-server installed in {install_dir}")
                        if _llama_server_supports_cuda_backend(dst):
                            installed_cuda = True
                            break
                        print("  [warn] Downloaded llama-server does not advertise CUDA; continuing search")
                if installed_cuda:
                    break
            if installed_cuda:
                return True
            print("  [warn] Could not provision a CUDA-capable llama runtime from prebuilt sources")
        elif backend == "rocm":
            asset = f"llama-{tag}-bin-ubuntu-rocm-7.2-x64.tar.gz"
            print(f"  Downloading pre-built llama-server (ROCm, {tag})...")
            if _download_release_asset(tag, asset, install_dir):
                print(f"  [ok] llama-server installed in {install_dir}")
                return True
        elif backend == "vulkan":
            asset = f"llama-{tag}-bin-ubuntu-vulkan-x64.tar.gz"
            print(f"  Downloading pre-built llama-server (Vulkan, {tag})...")
            if _download_release_asset(tag, asset, install_dir):
                print(f"  [ok] llama-server installed in {install_dir}")
                return True
        else:
            asset = f"llama-{tag}-bin-ubuntu-x64.tar.gz"
            print(f"  Downloading pre-built llama-server (CPU, {tag})...")
            if _download_release_asset(tag, asset, install_dir):
                print(f"  [ok] llama-server installed in {install_dir}")
                return True

    print("  Installing prebuilt llama-cpp-python CPU wheel as fallback...")
    if _ensure_cpu_wheel():
        if backend == "cuda":
            print("  [error] CPU-only fallback installed on a CUDA host. Run setup again after fixing CUDA runtime availability.")
            return False
        return True

    print("  Installing llama-cpp-python[server] as last resort (may compile)...")
    r = _pip_install("llama-cpp-python[server]", user=_IN_DOCKER)
    if r.returncode == 0:
        print("  [ok] llama-cpp-python[server] installed")
        if backend == "cuda":
            if _cuda_runtime_ready():
                return True
            print("  [error] Last-resort install succeeded but CUDA runtime is still unavailable")
            return False
        return True
    else:
        print("  [warn] Could not install llama.cpp runtime. Install manually later.")
    return False


def _json_get(url: str, timeout: int = 2) -> dict | None:
    import urllib.request, json

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "atenea-setup"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status < 200 or resp.status >= 300:
                return None
            payload = json.loads(resp.read())
            if isinstance(payload, dict):
                return payload
    except Exception:
        return None
    return None


def _local_llm_hosts() -> list[str]:
    hosts = ["127.0.0.1", "localhost"]

    for key in ("LLM_HOST",):
        val = os.getenv(key, "").strip()
        if val and val not in hosts:
            hosts.append(val)

    for key in ("OLLAMA_BASE_URL", "OLLAMA_URL", "LM_STUDIO_URL"):
        raw = os.getenv(key, "").strip()
        if not raw:
            continue
        try:
            parsed = urlparse(raw if "://" in raw else f"http://{raw}")
            host = (parsed.hostname or "").strip()
            if host and host not in hosts:
                hosts.append(host)
        except Exception:
            continue

    if _IN_DOCKER and "host.docker.internal" not in hosts:
        hosts.append("host.docker.internal")
    return hosts


def detect_running_local_models() -> list[dict[str, str]]:
    """Detect running local inference backends with at least one model available."""
    found: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    hosts = _local_llm_hosts()

    def _add(backend: str, url: str, models: int) -> None:
        if url in seen_urls:
            return
        seen_urls.add(url)
        found.append({"backend": backend, "url": url, "models": str(models)})

    # OpenAI-compatible endpoints (vLLM, llama.cpp server, LM Studio, others)
    openai_ports = [8000, 8080, 1234, 8010] + list(range(8001, 8021))
    for host in hosts:
        for port in openai_ports:
            base = f"http://{host}:{port}"
            data = _json_get(f"{base}/v1/models", timeout=1)
            if not data:
                continue
            items = data.get("data")
            if isinstance(items, list) and items:
                _add("openai-compatible", f"{base}/v1", len(items))

    # Ollama native API
    for host in hosts:
        base = f"http://{host}:11434"
        data = _json_get(f"{base}/api/tags", timeout=1)
        if not data:
            continue
        models = data.get("models")
        if isinstance(models, list) and models:
            _add("ollama", f"{base}", len(models))

    return found


def _can_prompt_inference_choice() -> bool:
    if os.getenv("ATENEA_INFERENCE_NONINTERACTIVE", "").strip().lower() in ("1", "true", "yes"):
        return False
    return bool(sys.stdin.isatty())


def _auto_inference_backend_choice() -> str:
    # Keep default simple and reliable for first-time local setups.
    backend = _detect_gpu_backend()
    if backend == "cuda" and platform.system().lower() == "linux":
        return "vllm"
    return "ollama"


def _prompt_inference_backend_choice() -> str:
    options = [
        ("ollama", "Ollama (Recommended)"),
        ("llamacpp", "llama.cpp"),
        ("vllm", "vLLM (Linux + NVIDIA CUDA)"),
        ("hf-local", "Hugging Face local (Transformers)"),
        ("skip", "Skip for now"),
    ]
    print("  No running local model server was detected.")
    print("  Choose a local backend to install:")
    for idx, (_key, label) in enumerate(options, start=1):
        print(f"    {idx}) {label}")
    default_choice = 1
    try:
        raw = input(f"  Select backend [{default_choice}]: ").strip()
    except EOFError:
        raw = ""
    if not raw:
        return options[default_choice - 1][0]
    if raw.isdigit():
        pick = int(raw)
        if 1 <= pick <= len(options):
            return options[pick - 1][0]
    raw = raw.lower()
    for key, _label in options:
        if raw == key:
            return key
    print("  [warn] Invalid selection. Falling back to Ollama.")
    return "ollama"


def _setup_ollama_local() -> bool:
    if shutil.which("ollama"):
        print("  [ok] Ollama already installed")
        return True

    system = platform.system().lower()
    if system == "linux":
        if not shutil.which("curl"):
            print("  [warn] curl is required to auto-install Ollama on Linux")
            print("         Install manually: https://ollama.com/download")
            return False
        print("  [info] Installing Ollama...")
        r = subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, capture_output=True, text=True)
        if r.returncode == 0 and shutil.which("ollama"):
            print("  [ok] Ollama installed")
            return True
        print("  [warn] Ollama installation failed")
        return False

    if system == "darwin":
        if shutil.which("brew"):
            print("  [info] Installing Ollama via Homebrew...")
            r = subprocess.run(["brew", "install", "ollama"], capture_output=True, text=True)
            if r.returncode == 0 and shutil.which("ollama"):
                print("  [ok] Ollama installed")
                return True
        print("  [warn] Could not auto-install Ollama on macOS")
        print("         Install manually from https://ollama.com/download")
        return False

    print("  [warn] Ollama auto-install is not available on this OS")
    print("         Install manually from https://ollama.com/download")
    return False


def _setup_vllm_local() -> bool:
    if platform.system().lower() != "linux":
        print("  [warn] vLLM setup is currently supported only on Linux")
        return False
    if _detect_gpu_backend() != "cuda":
        print("  [warn] vLLM requires an NVIDIA CUDA runtime")
        return False
    print("  [info] Installing vLLM...")
    r = _pip_install("vllm", user=_IN_DOCKER)
    if r.returncode != 0:
        print("  [warn] vLLM installation failed")
        return False
    check = subprocess.run([sys.executable, "-c", "import vllm"], capture_output=True, text=True)
    if check.returncode == 0:
        print("  [ok] vLLM installed")
        return True
    print("  [warn] vLLM install completed but import check failed")
    return False


def _setup_hf_local() -> bool:
    print("  [info] Installing local Hugging Face runtime (Transformers)...")
    r = _pip_install("torch", "transformers", "accelerate", "safetensors", "sentencepiece", user=_IN_DOCKER)
    if r.returncode != 0:
        print("  [warn] Hugging Face local runtime installation failed")
        return False
    check = subprocess.run(
        [sys.executable, "-c", "import torch, transformers, accelerate"],
        capture_output=True,
        text=True,
    )
    if check.returncode == 0:
        print("  [ok] Hugging Face local runtime installed")
    else:
        print("  [warn] Hugging Face runtime install completed but import check failed")
        return False

    host = os.getenv("ATENEA_HF_LOCAL_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.getenv("ATENEA_HF_LOCAL_PORT", "8010"))
    except ValueError:
        port = 8010
    model_id = os.getenv("ATENEA_HF_LOCAL_MODEL", "sshleifer/tiny-gpt2").strip() or "sshleifer/tiny-gpt2"
    script_path = os.path.join(BASE_DIR, "scripts", "hf_local_openai_server.py")
    if not os.path.exists(script_path):
        print("  [warn] hf-local server script not found")
        return True

    running = _json_get(f"http://{host}:{port}/v1/models", timeout=1)
    if running and isinstance(running.get("data"), list) and running.get("data"):
        print(f"  [ok] hf-local OpenAI endpoint already running at http://{host}:{port}/v1")
        return True

    print(f"  [info] Starting hf-local OpenAI endpoint on http://{host}:{port}/v1 ...")
    log_dir = os.path.join(DATA_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "hf-local-server.log")
    try:
        with open(log_file, "a", encoding="utf-8") as log:
            subprocess.Popen(
                [
                    sys.executable,
                    script_path,
                    "--model",
                    model_id,
                    "--host",
                    host,
                    "--port",
                    str(port),
                ],
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
    except Exception as e:
        print(f"  [warn] Could not start hf-local server automatically: {e}")
        return True

    for _ in range(15):
        probe = _json_get(f"http://{host}:{port}/v1/models", timeout=1)
        if probe and isinstance(probe.get("data"), list) and probe.get("data"):
            print(f"  [ok] hf-local endpoint is up at http://{host}:{port}/v1")
            return True
        time.sleep(1)

    print("  [warn] hf-local server process started but endpoint is not ready yet")
    print(f"         Check log: {log_file}")
    return True


def _setup_selected_inference_backend(choice: str) -> bool:
    choice = (choice or "").strip().lower()
    if choice == "skip":
        print("  [skip] Skipping local inference backend installation")
        return True
    if choice == "ollama":
        return _setup_ollama_local()
    if choice == "llamacpp":
        return setup_llamacpp()
    if choice == "vllm":
        return _setup_vllm_local()
    if choice == "hf-local":
        return _setup_hf_local()
    print(f"  [warn] Unknown inference backend choice: {choice}")
    return False


def setup_local_inference_backend() -> bool:
    running = detect_running_local_models()
    if running:
        print("  [ok] Local inference backend already running:")
        for item in running:
            print(f"       - {item['backend']} at {item['url']} ({item['models']} model(s))")
        return True

    mode = os.getenv("ATENEA_INFERENCE_SETUP", "").strip().lower()
    if mode not in ("prompt", "auto", "skip"):
        mode = "auto" if _IN_DOCKER else "prompt"

    if mode == "skip":
        print("  [skip] Local inference backend setup skipped by ATENEA_INFERENCE_SETUP=skip")
        return True

    chosen = os.getenv("ATENEA_INFERENCE_BACKEND", "").strip().lower()
    if not chosen:
        if mode == "prompt" and _can_prompt_inference_choice():
            chosen = _prompt_inference_backend_choice()
        else:
            chosen = _auto_inference_backend_choice()
            print(f"  [info] No running local model detected; auto-selecting backend: {chosen}")

    ok = _setup_selected_inference_backend(chosen)
    if not ok:
        print("  [warn] Selected local backend could not be installed automatically")
        return False

    running_after = detect_running_local_models()
    if running_after:
        print("  [ok] Local model backend is running")
        return True

    print("  [warn] Backend installed, but no local model server is running yet.")
    print("         Start your backend and load/pull a model, then run setup again.")
    if chosen == "ollama":
        print("         Example: ollama serve    (in another terminal)")
        print("                  ollama pull llama3.2:3b")
    elif chosen == "vllm":
        print("         Example: vllm serve Qwen/Qwen2.5-1.5B-Instruct")
    elif chosen == "hf-local":
        print("         Example: run a local Transformers server and expose /v1/models")
    return True


def check_deps():
    """Check for common missing dependencies."""
    missing = []
    for mod in ["fastapi", "uvicorn", "sqlalchemy", "bcrypt", "httpx", "dotenv"]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print(f"\n  [warn] Missing packages: {', '.join(missing)}")
        print(f"         Run: pip install -r requirements.txt")
    else:
        print("  [ok] All core dependencies installed")

    print("\n6. Local inference backend...")
    if not setup_local_inference_backend():
        print("  [warn] No local backend was fully configured automatically.")
        print("         You can continue setup and configure it later.")

    if os.name != "nt" and shutil.which("tmux") is None:
        print("\n  [warn] tmux not found")
        print("         Cookbook uses tmux for background downloads and model serves.")
        print("         Install it with your OS package manager, for example:")
        if sys.platform == "darwin":
            print("           brew install tmux")
        else:
            print("           sudo apt install tmux")
            print("           sudo pacman -S tmux")
            print("           sudo dnf install tmux")
    elif os.name != "nt":
        print("  [ok] tmux installed")


def check_arch():
    """Stop early, with guidance, if we're on Apple Silicon but running an
    Intel (x86_64) Python through Rosetta.

    A venv built with such an interpreter installs and loads compiled packages
    (bcrypt, pydantic-core, onnxruntime, …) for the wrong CPU architecture, then
    dies deep inside an import with a cryptic
    "(mach-o file, but is an incompatible architecture)" error. Catching it here
    turns that into one clear, actionable message.
    """
    if sys.platform != "darwin" or platform.machine() == "arm64":
        return  # Not macOS, or already an arm64-native interpreter — nothing to do.

    # platform.machine() == "x86_64": either a genuine Intel Mac (fine) or an x86
    # interpreter running under Rosetta on Apple Silicon (the case we must catch).
    try:
        translated = subprocess.run(
            ["sysctl", "-n", "sysctl.proc_translated"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        translated = ""
    if translated != "1":
        return  # Genuine Intel Mac — carry on.

    print("\n  [error] This is an Apple Silicon Mac, but setup is running under an")
    print("          Intel (x86_64) Python through Rosetta. Compiled packages would")
    print('          load as the wrong architecture and crash with "incompatible')
    print('          architecture" later on.')
    print("\n          Rebuild the environment with Homebrew's arm64 Python:")
    print("            brew install python@3.12          # if you don't have it yet")
    print("            rm -rf venv")
    print("            /opt/homebrew/bin/python3.12 -m venv venv")
    print("            ./venv/bin/pip install -r requirements.txt")
    print("            ./venv/bin/python app_setup.py")
    print("\n          Tip: ./start-macos.sh does all of this with the right Python.\n")
    sys.exit(1)


def _run_host_setup():
    """Full host-side setup: dirs, env, deps, DB, admin."""
    print("\n=== Atenea Setup ===\n")

    check_arch()

    print("1. Creating directories...")
    create_dirs()

    print("\n2. Environment file...")
    create_env()

    print("\n3. Checking dependencies...")
    check_deps()

    print("\n4. Initializing database...")
    try:
        init_database()
    except Exception as e:
        print(f"  [warn] Database init failed: {e}")
        print("         This is OK if dependencies aren't installed yet.")

    print("\n5. Creating initial admin...")

    admin_status, admin_user, admin_pass, show_pass = "failed", "", "", False

    try:
        admin_status, admin_user, admin_pass, show_pass = create_default_admin()
    except Exception as e:
        print(f"  [warn] Admin creation failed: {e}")
        admin_status = "failed"

    print("\n═══════════════════════════════════════")
    print("  Setup complete")
    print("═══════════════════════════════════════")

    if admin_status == "created":
        print(f"  Admin:  {admin_user}")
        if show_pass:
            print(f"  Password:  {admin_pass}")
        else:
            print("  Password:  (you entered it above)")
        print()
    if admin_status == "exists":
        print("  Admin account already exists — use your existing credentials.")
        print()
    elif admin_status == "skipped":
        print("  Admin creation skipped (missing dependencies).")
        print("  Run: pip install bcrypt && python app_setup.py\n")
    elif admin_status == "failed":
        print("  Admin creation failed. Check permissions on data/ directory.\n")


def _run_container_setup():
    """Inside-container setup: minimal, only what's needed at runtime."""
    print("  [setup] Creating directories...")
    create_dirs()
    print("  [setup] Environment file...")
    create_env()
    print("  [setup] Database...")
    init_database()
    print("  [setup] Admin account...")
    create_default_admin()
    print("  [setup] Local inference backend...")
    setup_local_inference_backend()


def main():
    if _IN_DOCKER:
        _run_container_setup()
    else:
        _run_host_setup()


if __name__ == "__main__":
    main()
