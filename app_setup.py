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

    try:
        __import__("llama_cpp")
    except ImportError:
        print('\n  [warn] llama-cpp-python server is not installed.')
        print('         Run: pip install "llama-cpp-python[server]"')
    else:
        print("  [ok] llama-cpp-python server installed")

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


def main():
    print("\n=== Atenea Setup ===\n")

    # Fail fast with a clear message if the CPU architecture is wrong (Apple
    # Silicon under an x86/Rosetta Python) before importing anything native.
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

    # start-macos.sh launches the server itself (on its own port) right after
    # this, so suppress the manual hint there to avoid a contradictory URL.
    if not os.getenv("ATENEA_SKIP_RUN_HINT"):
        print(f"  Start:  python -m uvicorn app:app --host 127.0.0.1 --port 7000")
        print(f"  Open:   http://localhost:7000\n")


if __name__ == "__main__":
    main()
