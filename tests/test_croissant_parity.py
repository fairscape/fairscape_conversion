#!/usr/bin/env python3
"""Parity: the unified croissant plugin must produce the SAME Croissant JSON as
the production ``ROCToTargetConverter`` + ``MAPPING_CONFIGURATION``, on real
RO-Crates (c2m2 crates carry schemas -> record sets; d4d crates carry root +
digital objects). Production code is untouched — this proves the CSV mapping
drives it to identical output.
"""

import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
C2M2_CRATES = sorted((HERE.parents[2] / "b2ai-metadata-generation" / "0.1-alpha"
                      / "c2m2-rocrate" / "src" / "test-data" / "example-crates"
                      ).glob("*/ro-crate-metadata.json"))
D4D_CRATES = sorted((HERE.parents[1] / "bridge" / "convertV2" / "examples").glob("*.rocrate.json"))
CRATES = C2M2_CRATES + D4D_CRATES


def _original(crate):
    from fairscape_models.conversion.converter import ROCToTargetConverter
    from fairscape_models.conversion.mapping.croissant import MAPPING_CONFIGURATION
    from fairscape_models.rocrate import ROCrateV1_2
    source = ROCrateV1_2.model_validate(crate)
    result = ROCToTargetConverter(source, MAPPING_CONFIGURATION).convert()
    return result.model_dump(by_alias=True, exclude_none=True) if result is not None else None


@pytest.mark.parametrize("path", CRATES, ids=lambda p: p.parent.name + "/" + p.name)
def test_croissant_parity(path):
    import fairscape_conversion.plugins.croissant as new
    crate = json.loads(path.read_text())
    try:
        want = _original(json.loads(json.dumps(crate)))
    except Exception as e:
        pytest.skip(f"crate does not validate for the production converter: {e}")
    got = new.convert("export", json.loads(json.dumps(crate)))
    assert json.dumps(got, sort_keys=True, default=str) == json.dumps(want, sort_keys=True, default=str)
