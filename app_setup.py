#!/usr/bin/env python3
"""Atenea — first-time setup script.

Creates data directories, initializes the database, and sets up an
initial admin user. Safe to re-run (skips what already exists).
"""

import os
import platform
import shutil
import subprocess
import sys

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


def _pip_install(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade"] + list(args),
        capture_output=True, text=True,
    )


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


def _ensure_cuda_wheel():
    """Force-install the CUDA wheel for llama-cpp-python inside a GPU-capable container."""
    marker = os.path.join(DATA_DIR, ".cuda-wheel-installed")
    if os.path.exists(marker):
        return True
    print("  [info] Installing CUDA wheel for llama-cpp-python...")
    r = _pip_install("--force-reinstall", "llama-cpp-python[server]",
                     "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cu124")
    if r.returncode == 0:
        open(marker, "w").close()
        print("  [ok] llama-cpp-python with CUDA installed")
        return True
    print("  [warn] CUDA wheel not available for this Python version")
    return False


def setup_llamacpp():
    """Auto-detect hardware and install pre-built llama-server or CUDA wheel."""
    existing = shutil.which("llama-server")
    while existing:
        try:
            r = subprocess.run([existing, "--version"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                print("  [ok] llama-server already installed")
                if _IN_DOCKER and _detect_gpu_backend() == "cuda":
                    _ensure_cuda_wheel()
                return
        except: pass
        print(f"  [warn] Removing broken llama-server at {existing}")
        os.remove(existing)
        existing = shutil.which("llama-server")

    try:
        __import__("llama_cpp")
        print("  [ok] llama-cpp-python already installed")
        if _IN_DOCKER and _detect_gpu_backend() == "cuda":
            _ensure_cuda_wheel()
        return
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
        backend = _detect_gpu_backend()
        if backend == "cuda":
            # Check if CUDA runtime (libcudart) is actually available
            _has_cudart = False
            try:
                r = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, timeout=10)
                _has_cudart = "libcudart" in r.stdout
            except: pass
            if not _has_cudart:
                _cuda_home = os.environ.get("CUDA_HOME", "/usr/local/cuda")
                _has_cudart = any(
                    os.path.isfile(os.path.join(d, f"libcudart.so.{v}"))
                    for d in [f"{_cuda_home}/lib64", f"{_cuda_home}/lib", "/usr/lib/x86_64-linux-gnu"]
                    for v in ("12", "11", "")
                )
            if not _has_cudart:
                print("  [info] NVIDIA GPU detected but CUDA runtime (libcudart) not found — skipping CUDA wheel")
                if _IN_DOCKER:
                    print("         Inside Docker with NVIDIA_VISIBLE_DEVICES=all but no libcudart — GPU passthrough may be incomplete")
                else:
                    print("         Install CUDA runtime: sudo apt install nvidia-cuda-toolkit")
                print("         Falling back to Vulkan binary...")
                backend = "vulkan"
            else:
                if _ensure_cuda_wheel():
                    return
                print("  [warn] CUDA wheel not available for your Python version, trying Vulkan binary...")
                backend = "vulkan"

        tag = _latest_llama_release_tag()
        if backend == "rocm":
            asset = f"llama-{tag}-bin-ubuntu-rocm-7.2-x64.tar.gz"
            label = "ROCm"
        elif backend in ("vulkan", "cuda"):  # cuda falls back to vulkan
            asset = f"llama-{tag}-bin-ubuntu-vulkan-x64.tar.gz"
            label = "Vulkan"
        else:
            asset = f"llama-{tag}-bin-ubuntu-x64.tar.gz"
            label = "CPU"
        print(f"  Downloading pre-built llama-server ({label}, {tag})...")
        if _download_release_asset(tag, asset, install_dir):
            print(f"  [ok] llama-server installed in {install_dir}")
            return

    print("  Installing llama-cpp-python[server] as fallback...")
    r = _pip_install("llama-cpp-python[server]")
    if r.returncode == 0:
        print("  [ok] llama-cpp-python[server] installed")
    else:
        print("  [warn] Could not install llama-server. Install manually later.")


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

    print("\n6. llama.cpp inference server...")
    setup_llamacpp()

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
    print("  [setup] LLM backend...")
    setup_llamacpp()


def main():
    if _IN_DOCKER:
        _run_container_setup()
    else:
        _run_host_setup()


if __name__ == "__main__":
    main()
