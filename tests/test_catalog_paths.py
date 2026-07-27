"""Verifies the three catalog scripts resolve their catalog directory
relative to their own file location, not the current working directory."""

import importlib.util
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CATALOG_DIR = REPO_ROOT / "data" / "catalog"

SCRIPTS = {
    "scrape_catalog": ("data/scrape_catalog.py", "OUTPUT_DIR"),
    "build_catalog": ("data/build_catalog.py", "BASE"),
    "validate_catalog": ("data/validate_catalog.py", "BASE"),
}


def _load_isolated(tmp_path, rel_path, module_name):
    """Copy the script into an isolated temp tree and execute it from there.

    build_catalog.py and validate_catalog.py run all their logic at module
    scope (no __main__ guard), so importing them from their real repo path
    would read/write/delete real catalog data. Executing a copy under
    tmp_path confines any such side effects there; exceptions raised after
    the path constant is assigned are swallowed since only that constant
    is under test here.
    """
    src = REPO_ROOT / rel_path
    dest = tmp_path / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)

    spec = importlib.util.spec_from_file_location(module_name, dest)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except BaseException:
        pass
    return module, dest


def _expected_dir_for(dest):
    return dest.resolve().parents[1] / "data" / "catalog"


def test_scrape_catalog_path_is_cwd_independent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module, dest = _load_isolated(tmp_path, "data/scrape_catalog.py", "scrape_catalog_isolated")
    assert module.OUTPUT_DIR == _expected_dir_for(dest)


def test_build_catalog_path_is_cwd_independent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module, dest = _load_isolated(tmp_path, "data/build_catalog.py", "build_catalog_isolated")
    assert module.BASE == _expected_dir_for(dest)


def test_validate_catalog_path_is_cwd_independent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module, dest = _load_isolated(tmp_path, "data/validate_catalog.py", "validate_catalog_isolated")
    assert module.BASE == _expected_dir_for(dest)


def test_real_scripts_use_file_relative_catalog_dir():
    for rel_path, var_name in SCRIPTS.values():
        text = (REPO_ROOT / rel_path).read_text()
        assert "PROJECT_ROOT = Path(__file__).resolve().parents[1]" in text
        assert 'CATALOG_DIR = PROJECT_ROOT / "data" / "catalog"' in text
        assert f"{var_name} = CATALOG_DIR" in text
        assert "/Users/" not in text
