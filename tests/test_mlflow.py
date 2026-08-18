"""mlflow plugin tests: golden file + determinism + one-way contract.

``input.json`` is a real records extraction from an MLflow 3.15 file-store
fixture (an 'iris-classifier' experiment: one training run with params,
metrics, a logged pandas dataset input, two artifacts, and an sklearn
LoggedModel, plus one nested child run), captured with a pinned
author/date_published so the conversion is fully deterministic;
``golden.json`` is the reviewed conversion.

Extraction itself (extract.py) talks to a live tracking store through the
mlflow client and is exercised by the nf/mlflow-fairscape harness
(tools/run-examples.sh), which also covers fairscape_models validation and
ARK stability across independent re-exports. These tests stay hermetic: no
mlflow import, no filesystem beyond the two fixtures.
"""

import json
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "mlflow"


def _load(name):
    with open(PLUGIN_DIR / name) as f:
        return json.load(f)


def test_mlflow_import_matches_golden():
    from fairscape_conversion.plugins.mlflow import convert

    assert convert("import", _load("input.json")) == _load("golden.json")


def test_mlflow_arks_are_deterministic():
    from fairscape_conversion.plugins.mlflow import convert

    records = _load("input.json")
    first = [n["@id"] for n in convert("import", records)["@graph"]]
    second = [n["@id"] for n in convert("import", _load("input.json"))["@graph"]]
    assert first == second
    assert len(first) == len(set(first)), "duplicate @ids in the crate"


def test_mlflow_nested_run_links_to_parent():
    from fairscape_conversion.plugins.mlflow import convert

    crate = convert("import", _load("input.json"))
    nodes = {n["@id"]: n for n in crate["@graph"]}
    children = [n for n in crate["@graph"] if n.get("isPartOf")
                and "Computation" in str(n.get("@type"))]
    assert children, "fixture has a nested child run"
    for child in children:
        parent_id = child["isPartOf"][0]["@id"]
        assert "Computation" in str(nodes[parent_id]["@type"])


def test_mlflow_schema_records_pass_through():
    from fairscape_conversion.plugins.mlflow import convert

    records = _load("input.json")
    assert records["schemas"], "fixture has a colspec schema"
    crate = convert("import", records)
    nodes = {n["@id"]: n for n in crate["@graph"]}
    for node in records["schemas"].values():
        assert nodes[node["@id"]] == node


def test_mlflow_export_unsupported():
    from fairscape_conversion.plugins.mlflow import convert

    with pytest.raises(NotImplementedError):
        convert("export", _load("golden.json"))
