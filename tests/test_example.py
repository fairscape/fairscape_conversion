"""The example plugin's golden-file test.

This is the green-field testing pattern for a NEW plugin (no pre-existing
reference converter to diff against): commit a representative ``input.json``
and the expected ``golden.json`` inside the plugin folder and assert the
conversion reproduces it. It also keeps ``plugins/example/`` — the template
people copy — from silently rotting as ``PluginBase`` evolves.
"""

import json
from pathlib import Path

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "plugins" / "example"


def _load(name):
    return json.loads((EXAMPLE_DIR / name).read_text())


def test_example_import_matches_golden():
    from fairscape_conversion.plugins import example

    assert example.convert("import", _load("input.json")) == _load("golden.json")
