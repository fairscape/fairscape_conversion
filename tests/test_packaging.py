"""The packaging manifest has to keep up with the plugins on disk.

pyproject maps the import name onto the repo root (``package-dir``), which
defeats setuptools' automatic discovery, so ``packages`` is an explicit list.
0.1.0 shipped with three plugins missing from it — they imported fine from a
checkout and were simply absent from the wheel. This catches that.
"""

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def _declared():
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return set(manifest["tool"]["setuptools"]["packages"])


def _on_disk():
    found = {"fairscape_conversion"}
    for init in ROOT.glob("*/__init__.py"):
        found.add(f"fairscape_conversion.{init.parent.name}")
    for init in ROOT.glob("plugins/*/__init__.py"):
        found.add(f"fairscape_conversion.plugins.{init.parent.name}")
    return found


def test_every_package_on_disk_is_declared():
    missing = _on_disk() - _declared()
    assert not missing, (
        "these packages exist but would not be installed — add them to "
        f"[tool.setuptools] packages in pyproject.toml: {sorted(missing)}"
    )


def test_no_declared_package_is_missing_from_disk():
    stale = _declared() - _on_disk()
    assert not stale, f"declared but not on disk: {sorted(stale)}"
