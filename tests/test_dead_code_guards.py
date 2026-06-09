from pathlib import Path


def test_legacy_fix_paths_script_removed():
    script = Path(__file__).resolve().parent.parent / "scripts" / "fix_paths.py"
    assert not script.exists()


def test_legacy_update_database_script_removed():
    script = Path(__file__).resolve().parent.parent / "scripts" / "update_database.py"
    assert not script.exists()


def test_legacy_faiss_migration_script_removed():
    script = Path(__file__).resolve().parent.parent / "scripts" / "migrate_faiss_to_chroma.py"
    assert not script.exists()
