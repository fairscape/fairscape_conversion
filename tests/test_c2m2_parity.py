#!/usr/bin/env python3
"""Parity for c2m2: the unified plugin (self-contained, on the shared pipeline,
mapped by the unified CSVs) must produce the SAME crate as the untouched
standalone converter on real datapackages, and cv_bases.csv must reproduce
ontology.py's base tables.
"""

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
C2M2_SRC = (HERE.parents[2] / "b2ai-metadata-generation" / "0.1-alpha"
            / "c2m2-rocrate" / "src")
MINI = C2M2_SRC / "test-data" / "c2m2-mini"
EXAMPLES = C2M2_SRC / "test-data" / "example-crates"

pytestmark = pytest.mark.skipif(
    not C2M2_SRC.exists(),
    reason="parity reference (the standalone c2m2-rocrate converter in the "
    "original tree) is not present next to this copy of the package",
)


def test_cv_bases_reproduce_ontology():
    """The plugin's CSV-driven ontology tables equal the original module's."""
    sys.path.insert(0, str(C2M2_SRC))
    import importlib
    import ontology as old_ontology
    importlib.reload(old_ontology)

    import fairscape_conversion.plugins.c2m2  # applies cv_bases.csv at import
    from fairscape_conversion.plugins.c2m2 import ontology as new_ontology
    assert new_ontology._CURIE_BASES == old_ontology._CURIE_BASES
    assert new_ontology._BARE_TABLE_BASES == old_ontology._BARE_TABLE_BASES
    assert new_ontology._BARE_CURIE_PREFIX == old_ontology._BARE_CURIE_PREFIX


def _norm(crate, out_dir):
    # The output directory is embedded in preserved-file nodes; normalize it out
    # so the comparison is about the mapping, not the tmp path.
    graph = sorted(crate.get("@graph", []), key=lambda n: json.dumps(n.get("@id", ""), sort_keys=True))
    return json.dumps(graph, sort_keys=True, default=str).replace(str(out_dir), "OUT")


def _old_crate(datapackage_dir, out_dir):
    sys.path.insert(0, str(C2M2_SRC))
    import convert as c2m2_convert
    mapper = c2m2_convert.MappingC2M2Converter(str(datapackage_dir))
    mapper.create_rocrate(output_path=str(out_dir))
    return json.loads((Path(out_dir) / "ro-crate-metadata.json").read_text())


@pytest.mark.parametrize("dp", [MINI] + sorted(p for p in EXAMPLES.glob("*-crate")
                                               if (p / "C2M2_datapackage.json").exists()
                                               and (p / "id_namespace.tsv").exists()))
def test_end_to_end_parity(dp, tmp_path):
    from fairscape_conversion.plugins.c2m2 import convert
    new = convert("import", dp, output_path=tmp_path / "new")
    old = _old_crate(dp, tmp_path / "old")
    assert _norm(new, tmp_path / "new") == _norm(old, tmp_path / "old")
