"""Every plugin ships a runnable example: an input fixture + the reviewed
golden output, both inside the plugin folder. Unlike the parity tests (which
need the original standalone converters checked out alongside), these are
hermetic — they run anywhere the package does.

- wrroc/input.json          a Workflow Run RO-Crate (CWL revsort, minimal)
- croissant/input.json      the crate the c2m2 example produces (schema-bearing)

(example/, snakemake/, cromwell/, mlflow/ have their own golden tests.)

The d4d and c2m2 conversions are not golden-compared here: both stamp the
output with the running fairscape_models version, and c2m2 also stamps
today's date, so the comparison broke on every release and every new day
rather than on a real change. Their goldens are still shipped — export_d4d
reads plugins/d4d/golden.json as its input crate, and the croissant example
input is pinned to the c2m2 golden (asserted below).
"""

import json
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"


def _norm(obj):
    """Down to plain JSON types, exactly how the goldens were serialized."""
    return json.loads(json.dumps(obj, default=str))


def _golden(plugin):
    return json.loads((PLUGINS / plugin / "golden.json").read_text())


def test_wrroc_example():
    from fairscape_conversion.plugins import wrroc

    source = json.loads((PLUGINS / "wrroc" / "input.json").read_text())
    assert _norm(wrroc.convert("import", source)) == _golden("wrroc")


def test_croissant_example():
    from fairscape_conversion.plugins import croissant

    source = json.loads((PLUGINS / "croissant" / "input.json").read_text())
    assert _norm(croissant.convert("export", source)) == _golden("croissant")


def test_croissant_input_is_c2m2_output():
    """The croissant example input is pinned to the c2m2 example's output, so
    the two examples chain: datapackage -> crate -> Croissant."""
    source = json.loads((PLUGINS / "croissant" / "input.json").read_text())
    assert source == _golden("c2m2")
