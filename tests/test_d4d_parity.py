#!/usr/bin/env python3
"""Parity: the unified d4d plugin must reproduce the standalone convertV2 bridge
byte-for-byte, both directions, on every example pair — plus a round-trip check.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
OLD_DIR = HERE.parents[1] / "bridge" / "convertV2"
EXAMPLES = OLD_DIR / "examples"
NAMES = ["AI_READI", "CHORUS", "CM4AI", "VOICE"]

pytestmark = pytest.mark.skipif(
    not OLD_DIR.exists(),
    reason="parity reference (the standalone convertV2 bridge from the "
    "original development tree) is not present next to this copy of the package",
)


def _load_old():
    sys.path.insert(0, str(OLD_DIR))
    fwd = importlib.import_module("d4d_to_rocrate")
    rev = importlib.import_module("rocrate_to_d4d")
    return fwd.convert, rev.convert


def _new():
    import fairscape_conversion.plugins.d4d as new
    return new


def _norm(obj) -> str:
    if isinstance(obj, dict) and "@graph" in obj:
        graph = sorted(obj["@graph"], key=lambda n: json.dumps(n.get("@id", ""), sort_keys=True))
        shell = {k: v for k, v in obj.items() if k != "@graph"}
        return json.dumps({"shell": shell, "graph": graph}, sort_keys=True, default=str)
    return json.dumps(obj, sort_keys=True, default=str)


@pytest.mark.parametrize("name", NAMES)
def test_forward_parity(name):
    old_forward, _ = _load_old()
    new = _new()
    d4d = yaml.safe_load((EXAMPLES / f"{name}.d4d.yaml").read_text())
    old_out = old_forward(json.loads(json.dumps(d4d)))
    new_out = new.convert("import", json.loads(json.dumps(d4d)))
    assert _norm(new_out) == _norm(old_out)


@pytest.mark.parametrize("name", NAMES)
def test_reverse_parity(name):
    _, old_reverse = _load_old()
    new = _new()
    crate = json.loads((EXAMPLES / f"{name}.rocrate.json").read_text())
    old_out = old_reverse(json.loads(json.dumps(crate)))
    new_out = new.convert("export", json.loads(json.dumps(crate)))
    assert _norm(new_out) == _norm(old_out)


@pytest.mark.parametrize("name", NAMES)
def test_roundtrip_via_new(name):
    new = _new()
    d4d = yaml.safe_load((EXAMPLES / f"{name}.d4d.yaml").read_text())
    crate = new.convert("import", json.loads(json.dumps(d4d)))
    back = new.convert("export", crate)
    # the crate's own identity survives the round trip
    assert back.get("id") == crate["@graph"][1]["@id"]
