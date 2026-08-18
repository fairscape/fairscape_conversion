#!/usr/bin/env python3
"""Parity: the unified wrroc plugin must reproduce the standalone converter
byte-for-byte, both directions, on every WRROC fixture — the proof the port
changed nothing observable. Kept green until the old code is retired.

The unified plugin now intentionally diverges in one place: the instrument's
input FormalParameters land on ``Computation.parameter`` (the standalone
converter drops them). Parity strips that key and compares everything else.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
OLD_DIR = HERE.parents[1] / "workflow_run_crate" / "wrroc"
EXAMPLES = HERE.parents[1] / "workflow_run_crate" / "examples"
FIXTURES = sorted(EXAMPLES.glob("*/ro-crate-metadata.json"))


def _load_old():
    """Import the standalone converter (its modules import each other by bare name)."""
    sys.path.insert(0, str(OLD_DIR))
    old_import = importlib.import_module("wrroc_to_evi")
    old_export = importlib.import_module("evi_to_wrroc")
    return old_import.convert, old_export.convert_to_wrroc


def _new():
    import fairscape_conversion.plugins.wrroc as new
    return new


def _norm(crate: dict) -> str:
    """Stable JSON with @graph sorted by @id, for order-insensitive comparison."""
    graph = sorted(crate.get("@graph", []), key=lambda n: json.dumps(n.get("@id", ""), sort_keys=True))
    shell = {k: v for k, v in crate.items() if k != "@graph"}
    return json.dumps({"shell": shell, "graph": graph}, sort_keys=True, default=str)


def _strip_divergences(crate: dict) -> dict:
    """Remove keys the unified plugin adds on purpose (Computation.parameter)."""
    for node in crate.get("@graph", []):
        node.pop("parameter", None)
    return crate


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.parent.name)
def test_import_parity(fixture):
    old_convert, _ = _load_old()
    new = _new()
    src = json.loads(fixture.read_text())
    old_out = old_convert(json.loads(json.dumps(src)))
    new_out = new.convert("import", json.loads(json.dumps(src)))
    assert _norm(_strip_divergences(new_out)) == _norm(old_out)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.parent.name)
def test_export_parity(fixture):
    old_convert, old_export = _load_old()
    new = _new()
    src = json.loads(fixture.read_text())
    evi = old_convert(json.loads(json.dumps(src)))          # shared EVI input
    old_wrroc = old_export(json.loads(json.dumps(evi)))
    new_wrroc = new.convert("export", json.loads(json.dumps(evi)))
    assert _norm(new_wrroc) == _norm(old_wrroc)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.parent.name)
def test_roundtrip_via_new(fixture):
    new = _new()
    src = json.loads(fixture.read_text())
    evi = new.convert("import", json.loads(json.dumps(src)))
    wrroc = new.convert("export", evi)
    # every original CreateAction returns under its original @id
    def actions(crate):
        return {n["@id"] for n in crate["@graph"]
                if "CreateAction" in (n.get("@type") if isinstance(n.get("@type"), list) else [n.get("@type")])}
    assert actions(src) == actions(wrroc)
