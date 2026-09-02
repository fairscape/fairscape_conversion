"""CPM plugin: golden-file conversion tests (hermetic — the in-repo example is
the real reference crate from https://zenodo.org/records/7676924, provenance
files only)."""

import json
import re
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "cpm"
INPUT_CRATE = PLUGIN_DIR / "input-crate"


def _load(name):
    return json.loads((PLUGIN_DIR / name).read_text())


def _norm(obj):
    """Down to plain JSON types, exactly how the goldens were serialized."""
    return json.loads(json.dumps(obj, default=str))


def _import_crate():
    from fairscape_conversion.plugins import cpm
    return cpm.convert("import", str(INPUT_CRATE))


def test_cpm_import_matches_golden():
    assert _norm(_import_crate()) == _load("golden.json")


def test_cpm_import_models_the_backbone():
    graph = _import_crate()["@graph"]
    by_ident = {n.get("identifier"): n for n in graph if n.get("identifier")}

    # Data transfers stay in the graph as plain prov:Activity nodes.
    transfers = [n for n in graph if n.get("additionalType") == "cpm:receiptActivity"]
    assert len(transfers) == 4
    assert all(n["@type"] == "prov:Activity" for n in transfers)

    # Main activities become Computations.
    mains = [n for n in graph if n.get("additionalType") == "cpm:mainActivity"]
    assert {n["name"] for n in mains} == {"preprocessing", "training", "mainActivityTesting"}
    assert all("https://w3id.org/EVI#Computation" in n["@type"] for n in mains)

    # The shared connector id stitches sender and receiver bundles into ONE node.
    connector = by_ident["ns_preprocessing:datasetTrainConnector"]
    prop_names = {p["name"] for p in connector["additionalProperty"]}
    assert {"cpm:senderBundleId", "cpm:receiverBundleId"} <= prop_names

    # Sub-activities hang off their bundle's main activity.
    train = by_ident["ns_training:training"]
    sub = by_ident["ns_training:trainIter0"]
    assert {"@id": train["@id"]} in sub["isPartOf"]

    # Bundle membership is subjectOf, never isPartOf: `isPartOf` would mark
    # every element "contained" and empty out the crate's derived outputs.
    bundle_files = {n["@id"] for n in graph
                    if n.get("additionalType") == "CPMProvenanceFile"}
    assert bundle_files
    for node in graph:
        contained = {r["@id"] for r in node.get("isPartOf") or []}
        assert not (contained & bundle_files)


def test_cpm_export_roundtrip_keeps_cpm_typing():
    from fairscape_conversion.plugins import cpm
    crate = _import_crate()

    assert _norm(cpm.convert("export", crate)) == _load("golden-export.json")

    provn_text = cpm.convert("export", crate, serialization="provn")
    exported = set(re.findall(r'prov:type="(cpm:[^"]+)"', provn_text))
    original = set()
    for f in INPUT_CRATE.glob("prov_*.provn"):
        original |= set(re.findall(r'prov:type="(cpm:[^"]+)"', f.read_text()))
    assert exported <= original            # round-trip never invents typing

    # Statements regroup into the original three bundles.
    from fairscape_conversion.plugins.cpm import provn
    doc = provn.parse_provn(provn_text)
    assert {b.ident for b in doc.bundles} == {
        "ns_preprocessing:bundle_preproc", "ns_training:bundle_training",
        "ns_eval:bundle_eval"}
    totals = {}
    for b in doc.bundles:
        for s in b.statements:
            totals[s.name] = totals.get(s.name, 0) + 1
    assert totals["used"] == 24 and totals["wasGeneratedBy"] == 18


def test_cpm_export_types_fresh_evi_crates():
    """A born-EVI crate (no fromCPM marker) gets the CPM backbone typing:
    top-level Computation -> mainActivity, unproduced input -> externalInput,
    terminal output -> senderConnector."""
    from fairscape_conversion.plugins import cpm

    crate = {"@graph": [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork",
         "about": {"@id": "ark:59853/rocrate-x"}},
        {"@id": "ark:59853/rocrate-x",
         "@type": ["Dataset", "https://w3id.org/EVI#ROCrate"], "name": "x"},
        {"@id": "ark:59853/comp-1",
         "@type": ["prov:Activity", "https://w3id.org/EVI#Computation"],
         "name": "run", "usedDataset": [{"@id": "ark:59853/data-in"}],
         "generated": [{"@id": "ark:59853/data-out"}]},
        {"@id": "ark:59853/data-in",
         "@type": ["prov:Entity", "https://w3id.org/EVI#Dataset"], "name": "in",
         "usedByComputation": [{"@id": "ark:59853/comp-1"}]},
        {"@id": "ark:59853/data-out",
         "@type": ["prov:Entity", "https://w3id.org/EVI#Dataset"], "name": "out",
         "generatedBy": [{"@id": "ark:59853/comp-1"}]},
    ]}
    provn_text = cpm.convert("export", crate, serialization="provn")
    assert 'prov:type="cpm:mainActivity"' in provn_text
    assert 'prov:type="cpm:externalInput"' in provn_text
    assert 'prov:type="cpm:senderConnector"' in provn_text


def test_provn_parser_survives_the_reference_quirks():
    """Ids with spaces, single-quoted values, `%%` datatypes, and `//` inside
    a namespace URI — the four traps in the real bundles."""
    from fairscape_conversion.plugins.cpm import provn

    doc = provn.parse_provn(
        "document\n"
        "  default <http://example.org/0/>\n"
        "  prefix ns <http://example.org/ns/>\n"
        "  bundle ns:b\n"
        "    entity(ns:WSI data, [prov:label='raw slides', ratio=\"0.5\" %% xsd:float])\n"
        "    used(ns:act, ns:WSI data, -)\n"
        "  endBundle\n"
        "endDocument\n")

    assert doc.default_ns == "http://example.org/0/"       # `//` never stripped
    assert doc.prefixes == {"ns": "http://example.org/ns/"}
    entity = doc.bundles[0].statements[0]
    assert entity.args == ["ns:WSI data"]                  # id containing a space
    assert ("prov:label", "raw slides", None) in entity.attrs      # single quotes
    assert ("ratio", "0.5", "xsd:float") in entity.attrs          # `%%` datatype
    assert doc.bundles[0].statements[1].args == ["ns:act", "ns:WSI data", None]


def test_provn_and_provjson_round_trip_the_reference_bundles():
    """Every real bundle survives provn -> text -> provn and provn -> json ->
    provn. Repeated element declarations of one id merge (PROV-JSON keys
    elements by identifier, and so does the importer)."""
    from fairscape_conversion.plugins.cpm import provn

    def statements(doc):
        relations, elements = [], {}
        for bundle in doc.bundles:
            for s in bundle.statements:
                args = list(s.args)
                while args and args[-1] is None:
                    args.pop()
                attrs = frozenset((k, str(v)) for k, v, _ in s.attrs)
                if s.name in ("entity", "activity", "agent"):
                    key = (bundle.ident, s.name, args[0])
                    elements[key] = elements.get(key, frozenset()) | attrs
                else:
                    relations.append((bundle.ident, s.name, tuple(args), tuple(sorted(attrs))))
        return sorted(relations) + sorted((k, tuple(sorted(v))) for k, v in elements.items())

    bundles = sorted(INPUT_CRATE.glob("*.provn"))
    assert len(bundles) == 4
    for path in bundles:
        doc = provn.parse_provn(path.read_text())
        assert statements(provn.parse_provn(provn.provn_dumps(doc))) == statements(doc)
        assert statements(provn.parse_provjson(provn.provjson_dumps(doc))) == statements(doc)
