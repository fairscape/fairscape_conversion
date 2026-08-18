"""cromwell plugin tests: golden file + parity against the standalone converter.

``input.json`` is a real records extraction from a Cromwell 92 run of the
standalone converter's letters-scatter example (chain + scatter + one
docker-pinned task), captured with a pinned author/date_published so the
conversion is fully deterministic; ``golden.json`` is the reviewed conversion.

The parity test runs BOTH converters — this plugin and the untouched
standalone ``nf/cromwell-fairscape`` — on the example's live metadata.json and
requires identical crates modulo the run timestamp. It needs the example to
have been run (tools/run-examples.sh there, requires the Cromwell jar), so it
skips when metadata.json is absent. The standalone harness also covers the
live path: fairscape_models validation and ARK stability across independent
Cromwell re-runs.
"""

import copy
import json
import os
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "cromwell"
STANDALONE = Path(__file__).resolve().parents[2] / "nf" / "cromwell-fairscape"
EXAMPLE_METADATA = STANDALONE / "examples" / "letters-scatter" / "metadata.json"


def _load(name):
    with open(PLUGIN_DIR / name) as f:
        return json.load(f)


def test_cromwell_import_matches_golden():
    from fairscape_conversion.plugins import cromwell
    assert cromwell.convert("import", _load("input.json")) == _load("golden.json")


def test_cromwell_arks_are_deterministic():
    from fairscape_conversion.plugins import cromwell
    a = cromwell.convert("import", _load("input.json"))
    b = cromwell.convert("import", _load("input.json"))
    assert [n["@id"] for n in a["@graph"]] == [n["@id"] for n in b["@graph"]]


def test_cromwell_schema_records_pass_through():
    """A pre-built Schema node in records['schemas'] is emitted verbatim,
    linked from its Dataset via evi:Schema, and listed in hasPart."""
    from fairscape_conversion.core.arks import mint_ark
    from fairscape_conversion.plugins import cromwell

    records = _load("input.json")
    path = sorted(records["files"])[0]
    schema_node = {
        "@id": "ark:59853/schema-test-0000000",
        "@type": "https://w3id.org/EVI#Schema",
        "name": "Schema for test",
        "description": "hand-built schema node for the pass-through test",
        "properties": {},
    }
    records["schemas"] = {path: dict(schema_node)}

    crate = cromwell.convert("import", records)
    by_id = {n["@id"]: n for n in crate["@graph"]}
    assert by_id[schema_node["@id"]] == schema_node

    info = records["files"][path]
    dataset_ark = mint_ark(records["settings"]["naan"], "dataset",
                           os.path.basename(path.rstrip("/")) or path,
                           info["ark_source"])
    assert by_id[dataset_ark]["evi:Schema"] == {"@id": schema_node["@id"]}
    root = crate["@graph"][1]
    assert {"@id": schema_node["@id"]} in root["hasPart"]


def test_cromwell_export_unsupported():
    from fairscape_conversion.plugins import cromwell
    with pytest.raises(Exception):
        cromwell.convert("export", _load("golden.json"))


def _normalize_timestamp(crate):
    """Replace every occurrence of the crate's datePublished (the only
    run-of-the-converter-dependent value) with a fixed token."""
    crate = copy.deepcopy(crate)
    stamp = crate["@graph"][1]["datePublished"]

    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return "DATE" if x == stamp else x

    return walk(crate)


@pytest.mark.skipif(not EXAMPLE_METADATA.exists(),
                    reason="letters-scatter metadata.json not present; run "
                    "nf/cromwell-fairscape/tools/run-examples.sh first")
def test_cromwell_parity_with_standalone(tmp_path):
    """The plugin must produce the SAME crate as the untouched standalone
    converter on a real Cromwell metadata file (modulo timestamp)."""
    from fairscape_conversion.plugins import cromwell
    plugin_crate = cromwell.convert("import", str(EXAMPLE_METADATA),
                                    crate_dir=str(tmp_path / "plugin"))

    sys.path.insert(0, str(STANDALONE))
    try:
        from cromwell_fairscape import main as standalone_main
        out = tmp_path / "standalone" / "ro-crate-metadata.json"
        # parity is defined on the crate as BUILT; the standalone's derived
        # artifacts (link inverses, evidence graph, linkml, datasheet — on by
        # default, delegated to fairscape-cli) rewrite the crate afterwards
        standalone_main([str(EXAMPLE_METADATA), "-o", str(out),
                         "--no-link-inverses", "--no-evidence-graph",
                         "--no-linkml", "--no-datasheet"])
        standalone_crate = json.loads(out.read_text())
    finally:
        sys.path.remove(str(STANDALONE))
        sys.modules.pop("cromwell_fairscape", None)

    assert _normalize_timestamp(plugin_crate) == _normalize_timestamp(standalone_crate)
