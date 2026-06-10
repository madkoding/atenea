from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_remote_linux_setup_attempts_ollama_install_when_possible():
    src = _read("routes/cookbook_routes.py")
    assert "if ! command -v ollama >/dev/null 2>&1; then " in src
    assert "sudo -n true >/dev/null 2>&1" in src
    assert "curl -fsSL https://ollama.com/install.sh | sh" in src


def test_remote_linux_setup_warns_when_noninteractive_sudo_blocks_ollama_install():
    src = _read("routes/cookbook_routes.py")
    assert "setup cannot prompt for sudo password" in src
    assert "Install it manually in a terminal" in src
