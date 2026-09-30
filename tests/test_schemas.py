"""`core.schemas`: the shared Schema-node step the workflow importers use.

The inference is `fairscape_models.schema`; what is pinned here is the part
this package owns — which files are considered, the deterministic ARK, the
node shape — and that the cromwell importer emits Schema nodes through it
without any `fairscape_cli` import. The tabular reader (frictionless) is an
optional extra of fairscape-models, so the reading tests skip without it.
"""

import json
from pathlib import Path

import pytest

from fairscape_conversion.core import schemas

HERE = Path(__file__).resolve().parent
WDL = HERE.parent / "examples" / "wdl-variant-calling"
TSV = WDL / "results" / "variant_summary.tsv"


def test_supported_follows_the_models_extension_map():
    assert schemas.supported("a/b/summary.tsv")
    assert schemas.supported("counts.CSV")
    assert schemas.supported("store.h5")
    assert not schemas.supported("reads.fastq.gz")
    assert not schemas.supported("results/")


def test_schema_ark_is_deterministic_and_distinct_from_the_dataset():
    from fairscape_conversion.core.arks import mint_ark
    a = schemas.schema_ark("59853", "summary.tsv", "/runs/1/summary.tsv")
    b = schemas.schema_ark("59853", "summary.tsv", "/runs/1/summary.tsv")
    assert a == b and a.startswith("ark:59853/schema-")
    assert a != mint_ark("59853", "dataset", "summary.tsv", "/runs/1/summary.tsv")
    assert a != schemas.schema_ark("59853", "summary.tsv", "/runs/2/summary.tsv")


def test_schema_node_reads_a_tsv():
    pytest.importorskip("frictionless")
    if not TSV.exists():
        pytest.skip("wdl example outputs not checked out")
    node = schemas.schema_node(str(TSV), naan="59853",
                               display_path="results/variant_summary.tsv",
                               dataset_source="x", tool="test")
    assert node["@id"] == schemas.schema_ark("59853", "variant_summary.tsv", "x")
    assert node["name"] == "Schema for variant_summary.tsv"
    assert "by test" in node["description"]
    assert node["properties"], "columns were read"
    json.dumps(node)  # plain data, serialisable as-is


def test_schema_node_swallows_a_bad_file(capsys, tmp_path):
    pytest.importorskip("frictionless")
    bad = tmp_path / "binary.csv"
    bad.write_bytes(b"\x1f\x8b\x08\x00garbage\x00\x00")
    node = schemas.schema_node(str(bad), naan="59853", display_path="binary.csv",
                               dataset_source="x", tool="test")
    # either the reader coped (a node) or it did not (None + a warning); it
    # must never raise
    if node is None:
        assert "schema inference failed" in capsys.readouterr().err


def test_cromwell_import_emits_schema_nodes_without_the_cli():
    pytest.importorskip("frictionless")
    meta = WDL / "run" / "metadata.json"
    if not (meta.exists() and TSV.exists()):
        pytest.skip("wdl example not checked out")
    from fairscape_conversion.plugins import cromwell
    crate = cromwell.convert("import", str(meta), crate_dir=str(WDL), schemas=True)
    nodes = [n for n in crate["@graph"] if "Schema" in str(n.get("@type"))]
    assert nodes, "schemas=True produced no Schema nodes"
    assert all(n["@id"].startswith("ark:59853/schema-") for n in nodes)
