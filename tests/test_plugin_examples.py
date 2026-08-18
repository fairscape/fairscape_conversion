"""Every plugin ships a runnable example: an input fixture + the reviewed
golden output, both inside the plugin folder. Unlike the parity tests (which
need the original standalone converters checked out alongside), these are
hermetic — they run anywhere the package does.

- wrroc/input.json          a Workflow Run RO-Crate (CWL revsort, minimal)
- d4d/input.yaml            a real D4D datasheet (AI-READI)
- c2m2/input-datapackage/   a miniature CFDE C2M2 datapackage (TSVs + schema)
- croissant/input.json      the crate the c2m2 example produces (schema-bearing)

(example/, snakemake/, cromwell/, mlflow/ have their own golden tests.)
"""

import json
from pathlib import Path

import pytest
import yaml

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


def test_d4d_example():
    from fairscape_conversion.plugins import d4d

    source = yaml.safe_load((PLUGINS / "d4d" / "input.yaml").read_text())
    assert _norm(d4d.convert("import", source)) == _golden("d4d")


def test_c2m2_example(tmp_path, monkeypatch):
    from fairscape_conversion.plugins import c2m2

    # Sandboxed with relative paths: the converter embeds its invocation paths
    # in the crate's provenance command and writes the crate + preserved source
    # files to disk, so this keeps the golden machine-independent and the repo
    # unwritten.
    import shutil

    shutil.copytree(PLUGINS / "c2m2" / "input-datapackage", tmp_path / "input-datapackage")
    monkeypatch.chdir(tmp_path)
    crate = c2m2.convert("import", "input-datapackage", output_path="c2m2-example-crate")
    assert _norm(crate) == _golden("c2m2")


def test_croissant_example():
    from fairscape_conversion.plugins import croissant

    source = json.loads((PLUGINS / "croissant" / "input.json").read_text())
    assert _norm(croissant.convert("export", source)) == _golden("croissant")


def test_croissant_input_is_c2m2_output():
    """The croissant example input is pinned to the c2m2 example's output, so
    the two examples chain: datapackage -> crate -> Croissant."""
    source = json.loads((PLUGINS / "croissant" / "input.json").read_text())
    assert source == _golden("c2m2")
