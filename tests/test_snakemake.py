"""snakemake plugin golden-file test (the green-field pattern from NEW-PLUGIN.md).

``input.json`` is a real run-records dump from snakemake-report-plugin-fairscape
(its letters-chain example, captured via SNAKEMAKE_FAIRSCAPE_DUMP_RECORDS);
``golden.json`` is the reviewed conversion. The records carry their own
``date_published``, so the conversion is fully deterministic.

The report plugin's own harness (nf/snakemake-fairscape/tools/run-examples.sh)
covers the live path: crate validation via fairscape_models, derived artifacts,
and ARK stability across re-runs.
"""

import json
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "snakemake"


def _load(name):
    with open(PLUGIN_DIR / name) as f:
        return json.load(f)


def test_snakemake_import_matches_golden():
    from fairscape_conversion.plugins import snakemake
    assert snakemake.convert("import", _load("input.json")) == _load("golden.json")


def test_snakemake_arks_are_deterministic():
    from fairscape_conversion.plugins import snakemake
    a = snakemake.convert("import", _load("input.json"))
    b = snakemake.convert("import", _load("input.json"))
    assert [n["@id"] for n in a["@graph"]] == [n["@id"] for n in b["@graph"]]


def test_snakemake_export_unsupported():
    import pytest
    from fairscape_conversion.plugins import snakemake
    with pytest.raises(Exception):
        snakemake.convert("export", _load("golden.json"))
