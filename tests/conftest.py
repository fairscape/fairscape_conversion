"""Make ``import fairscape_conversion.*`` resolve to THIS copy of the package
(the directory above tests/), not whatever editable install happens to be on
sys.path — and keep the standalone converters' bare-named modules (each has its
own ``parsers.py`` etc.) from cross-contaminating ``sys.modules`` between tests.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]          # .../conversion (package root)

_spec = importlib.util.spec_from_file_location(
    "fairscape_conversion", ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)])
_pkg = importlib.util.module_from_spec(_spec)
sys.modules["fairscape_conversion"] = _pkg
_spec.loader.exec_module(_pkg)

# Parity tests look for the untouched original converters next to the package
# (the original development tree's layout); they skip when those trees are absent.
SIBLINGS = ROOT.parents[0]
if str(SIBLINGS) not in sys.path:
    sys.path.insert(0, str(SIBLINGS))

# Bare module names shared across the standalone wrroc / d4d / c2m2 converters.
_COLLIDING = {"parsers", "convert", "ontology", "base",
              "wrroc_to_evi", "evi_to_wrroc", "d4d_to_rocrate", "rocrate_to_d4d"}


@pytest.fixture(autouse=True)
def _isolate_old_modules():
    """Purge the colliding bare-name modules before and after each test so every
    test re-imports the intended converter from the dir it puts first on the path."""
    def purge():
        for name in list(sys.modules):
            if name in _COLLIDING:
                del sys.modules[name]
    purge()
    yield
    purge()
