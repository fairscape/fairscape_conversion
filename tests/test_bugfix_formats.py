"""Regression tests for the d4d / croissant / wrroc / cpm bugs in bugs.md
(the 2026-10-12 bug hunt). Each test is named after its bug id and builds a
small synthetic input, so nothing here depends on the bug hunt's scratch files.
"""

import copy
import json
from collections import Counter
from pathlib import Path

import pydantic
import pytest

ROOT = Path(__file__).resolve().parents[1]
D4D_CRATE = ROOT / "examples" / "out" / "d4d" / "ro-crate-metadata.json"
CPM_INPUT_CRATE = ROOT / "plugins" / "cpm" / "input-crate"


# ============================================================================
# d4d / croissant
# ============================================================================

def test_D2_d4d_without_license_fails_with_a_clear_message():
    from fairscape_conversion.plugins import d4d
    datasheet = {"id": "https://example.org/ds", "title": "Minimal datasheet",
                 "description": "A datasheet that names no license."}
    with pytest.raises(ValueError, match="no license") as info:
        d4d.convert("import", datasheet)
    assert not isinstance(info.value, pydantic.ValidationError)


def test_D2_d4d_with_license_still_imports():
    from fairscape_conversion.plugins import d4d
    crate = d4d.convert("import", {"id": "https://example.org/ds", "title": "T",
                                   "description": "A licensed datasheet.",
                                   "license": "CC-BY-4.0"})
    root = crate["@graph"][1]
    assert root["license"] == "CC-BY-4.0"


def test_D1_croissant_export_of_d4d_crate():
    """The shipped AI-READI d4d crate holds list-valued rai:* fields."""
    from fairscape_conversion.plugins import croissant
    crate = json.loads(D4D_CRATE.read_text())
    out = croissant.convert("export", crate)
    assert isinstance(out["rai:dataCollection"], list)


@pytest.mark.parametrize("field", ["rai:dataCollectionType", "rai:dataPreprocessingProtocol",
                                   "rai:dataAnnotationPlatform", "rai:dataAnnotationAnalysis"])
def test_D1_croissant_export_accepts_plain_string_rai(field):
    from fairscape_conversion.plugins import croissant
    crate = json.loads(D4D_CRATE.read_text())
    root = next(n for n in crate["@graph"] if n.get("@id") == "https://fairhub.io/datasets/2")
    root[field] = "One plain statement."
    out = croissant.convert("export", crate)
    assert out[field] == "One plain statement."


def test_C7_d4d_import_then_croissant_export():
    from fairscape_conversion.plugins import croissant, d4d
    datasheet = {
        "id": "https://example.org/ds", "title": "Chained", "license": "CC0-1.0",
        "description": "A datasheet chained into a Croissant export.",
        "collection_mechanisms": [{"name": "survey", "description": "web survey"},
                                  {"name": "sensor", "description": "wearables"}],
    }
    crate = d4d.convert("import", datasheet)
    out = croissant.convert("export", crate)
    assert len(out["rai:dataCollection"]) == 2


# ============================================================================
# wrroc
# ============================================================================

def _wrroc_crate(root_extra=None, actions=None, extra_nodes=()):
    root = {"@id": "./", "@type": "Dataset", "name": "mini run", "datePublished": "2024-01-01",
            "conformsTo": [{"@id": "https://w3id.org/ro/wfrun/process/0.5"}],
            "license": "MIT", "hasPart": [{"@id": "in.txt"}, {"@id": "out.txt"}]}
    root.update(root_extra or {})
    graph = [{"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "about": {"@id": "./"},
              "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"}}, root,
             {"@id": "#tool", "@type": "SoftwareApplication", "name": "mytool"},
             {"@id": "in.txt", "@type": "File", "name": "in.txt"},
             {"@id": "out.txt", "@type": "File", "name": "out.txt"},
             {"@id": "#alice", "@type": "Person", "name": "Alice"}]
    graph += actions if actions is not None else [
        {"@id": "#run1", "@type": "CreateAction", "name": "run 1",
         "instrument": {"@id": "#tool"}, "object": [{"@id": "in.txt"}],
         "result": [{"@id": "out.txt"}], "agent": {"@id": "#alice"},
         "endTime": "2024-01-01T00:00:00"}]
    graph += list(extra_nodes)
    return {"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph}


def _evi_root(crate):
    return next(n for n in crate["@graph"] if "https://w3id.org/EVI#ROCrate" in n.get("@type", []))


def test_W1_wrroc_license_as_entity_reference():
    from fairscape_conversion.plugins import wrroc
    lic = "http://spdx.org/licenses/CC0-1.0"
    evi = wrroc.to_evi(_wrroc_crate(root_extra={"license": {"@id": lic}}))
    assert _evi_root(evi)["license"] == lic
    back = wrroc.to_wrroc(evi)
    root = next(n for n in back["@graph"] if n.get("@id") == "./")
    assert root["license"] == {"@id": lic}


def test_W1_wrroc_license_as_list():
    from fairscape_conversion.plugins import wrroc
    evi = wrroc.to_evi(_wrroc_crate(root_extra={"license": [
        "https://spdx.org/licenses/CC-BY-4.0.html", {"@id": "https://spdx.org/licenses/MIT"}]}))
    lic = _evi_root(evi)["license"]
    assert "CC-BY-4.0" in lic and "MIT" in lic


def test_W2_wrroc_list_valued_encoding_format():
    from fairscape_conversion.plugins import wrroc
    crate = _wrroc_crate()
    for n in crate["@graph"]:
        if n["@id"] == "in.txt":
            n["encodingFormat"] = ["text/plain",
                                   {"@id": "https://www.nationalarchives.gov.uk/PRONOM/x-fmt/111"}]
    evi = wrroc.to_evi(crate)
    infile = next(n for n in evi["@graph"] if n.get("identifier") == "in.txt")
    assert infile["format"] == "text/plain"


def test_W3_wrroc_software_without_name():
    from fairscape_conversion.plugins import wrroc
    crate = _wrroc_crate()
    for n in crate["@graph"]:
        if n["@id"] == "#tool":
            del n["name"]
    evi = wrroc.to_evi(crate)
    tool = next(n for n in evi["@graph"] if n.get("identifier") == "#tool")
    assert tool["name"] == "tool"


def test_W4_wrroc_export_parameter_ids_are_per_run():
    from fairscape_conversion.plugins import wrroc
    actions = []
    for i, val in ((1, "0.5"), (2, "0.9")):
        actions += [
            {"@id": f"#run{i}", "@type": "CreateAction", "name": f"Run of workflow step {i}",
             "instrument": {"@id": "#tool"}, "object": [{"@id": "in.txt"}, {"@id": f"#pv{i}"}],
             "result": [{"@id": "out.txt"}], "agent": {"@id": "#alice"},
             "endTime": "2024-01-01T00:00:00"},
            {"@id": f"#pv{i}", "@type": "PropertyValue", "name": "threshold", "value": val}]
    back = wrroc.to_wrroc(wrroc.to_evi(_wrroc_crate(actions=actions)))
    counts = Counter(n["@id"] for n in back["@graph"])
    assert not {k: v for k, v in counts.items() if v > 1}
    by_id = {n["@id"]: n for n in back["@graph"]}
    for action in (n for n in back["@graph"] if n["@type"] == "CreateAction"):
        values = [by_id[o["@id"]]["value"] for o in action["object"]
                  if by_id.get(o["@id"], {}).get("@type") == "PropertyValue"]
        expected = "0.5" if action["name"].endswith("1") else "0.9"
        assert values == [expected]


# ============================================================================
# cpm
# ============================================================================

TEST_PROVN = """document
  prefix ex <http://example.org/ex#>
  prefix ex2 <http://example.org/other#>
  prefix cpm <https://www.commonprovenancemodel.org/cpm-namespace-v1-0/>

  bundle ex:bundle1
    prefix ex <http://example.org/ex#>
    prefix ex2 <http://example.org/other#>

    activity(ex:main, 2024-05-01T10:00:00, 2024-05-01T11:00:00, [prov:type="cpm:mainActivity", prov:label="Main run"])
    activity(ex:step, 2024-05-01T10:00:00, 2024-05-01T11:00:00, [prov:label="Step one"])
    entity(ex:input, [prov:label="input.csv"])
    entity(ex2:input, [prov:label="other input.csv"])
    entity(ex:result, [prov:label="result.csv"])
    agent(ex:alice, [prov:type="prov:Person", prov:label="Alice"])
    agent(ex:org, [prov:type="cpm:senderAgent", prov:label="Org"])
    used(ex:step, ex:input, 2024-05-01T10:00:00)
    used(ex:step, ex2:input, 2024-05-01T10:00:00)
    wasGeneratedBy(ex:result, ex:step, 2024-05-01T11:00:00)
    wasDerivedFrom(ex:result, ex:input, -, -, -)
    wasAssociatedWith(ex:step, ex:alice, -)
    wasAttributedTo(ex:result, ex:org)
    actedOnBehalfOf(ex:alice, ex:org, -)
    wasInformedBy(ex:main, ex:step)
  endBundle
endDocument
"""


def _provjson_from_prov_library():
    """The same bundle as TEST_PROVN, written by the `prov` package."""
    prov_model = pytest.importorskip("prov.model")
    from datetime import datetime
    doc = prov_model.ProvDocument()
    doc.add_namespace("ex", "http://example.org/ex#")
    doc.add_namespace("ex2", "http://example.org/other#")
    doc.add_namespace("cpm", "https://www.commonprovenancemodel.org/cpm-namespace-v1-0/")
    b = doc.bundle("ex:bundle1")
    t0, t1 = datetime(2024, 5, 1, 10), datetime(2024, 5, 1, 11)
    b.activity("ex:main", t0, t1, {"prov:type": "cpm:mainActivity", "prov:label": "Main run"})
    b.activity("ex:step", t0, t1, {"prov:label": "Step one"})
    b.entity("ex:input", {"prov:label": "input.csv"})
    b.entity("ex2:input", {"prov:label": "other input.csv"})
    b.entity("ex:result", {"prov:label": "result.csv"})
    b.agent("ex:alice", {"prov:type": prov_model.PROV["Person"], "prov:label": "Alice"})
    b.agent("ex:org", {"prov:type": "cpm:senderAgent", "prov:label": "Org"})
    b.used("ex:step", "ex:input", t0)
    b.used("ex:step", "ex2:input", t0)
    b.wasGeneratedBy("ex:result", "ex:step", t1)
    b.wasDerivedFrom("ex:result", "ex:input")
    b.wasAssociatedWith("ex:step", "ex:alice")
    b.wasAttributedTo("ex:result", "ex:org")
    b.actedOnBehalfOf("ex:alice", "ex:org")
    b.wasInformedBy("ex:main", "ex:step")
    return json.loads(doc.serialize(format="json"))


def _cpm_source(fname, payload):
    crate = {"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "about": {"@id": "./"}},
        {"@id": "./", "@type": "Dataset", "name": "test", "datePublished": "2024-06-01",
         "license": "CC0-1.0",
         "conformsTo": [{"@id": "https://w3id.org/cpm/ro-crate/0.1"}], "hasPart": [{"@id": fname}]},
        {"@id": fname, "@type": ["File", "CPMProvenanceFile"], "name": fname}]}
    return {"crate": crate, "bundles": {fname: payload}}


@pytest.fixture(params=["provn", "provjson"])
def cpm_imported(request):
    from fairscape_conversion.plugins import cpm
    if request.param == "provn":
        source = _cpm_source("test.provn", TEST_PROVN)
    else:
        source = _cpm_source("test.json", _provjson_from_prov_library())
    graph = cpm.convert("import", source)["@graph"]
    return {n.get("name"): n for n in graph}, graph


def test_CPM1_relation_times_are_not_entities(cpm_imported):
    _, graph = cpm_imported
    phantoms = [n for n in graph if str(n.get("identifier", "")).startswith("2024-05")]
    assert phantoms == []


def test_CPM1_activity_times_are_kept(cpm_imported):
    by_name, _ = cpm_imported
    step = by_name["Step one"]
    assert step["dateCreated"].startswith("2024-05-01T11:00:00")
    assert step["startTime"].startswith("2024-05-01T10:00:00")


def test_CPM1_was_associated_with_sets_run_by(cpm_imported):
    by_name, _ = cpm_imported
    alice = by_name["Alice"]
    assert by_name["Step one"]["runBy"] == {"@id": alice["@id"]}


def test_CPM1_person_agent_stays_person(cpm_imported):
    by_name, _ = cpm_imported
    assert by_name["Alice"]["@type"] == "Person"


def test_CPM1_informed_by_and_delegation_are_kept(cpm_imported):
    by_name, _ = cpm_imported
    assert by_name["Main run"]["prov:wasInformedBy"] == [{"@id": by_name["Step one"]["@id"]}]
    assert by_name["Alice"]["prov:actedOnBehalfOf"] == [{"@id": by_name["Org"]["@id"]}]


def _workflow_evi():
    """A WRROC workflow run (one workflow action, two tool steps; one tool has
    an absolute-URL @id, the agent is an ORCID) imported to EVI."""
    from fairscape_conversion.plugins import wrroc
    orcid = "https://orcid.org/0000-0002-1825-0097"
    tool_url = "https://www.imagemagick.org/"
    graph = [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "about": {"@id": "./"},
         "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"}},
        {"@id": "./", "@type": "Dataset", "name": "wf run", "datePublished": "2024-01-01",
         "license": "MIT", "mainEntity": {"@id": "wf.cwl"},
         "conformsTo": [{"@id": "https://w3id.org/ro/wfrun/workflow/0.5"}]},
        {"@id": "wf.cwl", "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
         "name": "wf"},
        {"@id": tool_url, "@type": "SoftwareApplication", "name": "ImageMagick"},
        {"@id": "#sort", "@type": "SoftwareApplication", "name": "sort"},
        {"@id": "in.txt", "@type": "File", "name": "in.txt"},
        {"@id": "mid.txt", "@type": "File", "name": "mid.txt"},
        {"@id": "out.txt", "@type": "File", "name": "out.txt"},
        {"@id": orcid, "@type": "Person", "name": "Josiah Carberry"},
        {"@id": "#wfrun", "@type": "CreateAction", "name": "workflow run",
         "instrument": {"@id": "wf.cwl"}, "object": [{"@id": "in.txt"}],
         "result": [{"@id": "out.txt"}], "agent": {"@id": orcid},
         "startTime": "2024-01-01T09:00:00", "endTime": "2024-01-01T12:00:00"},
        {"@id": "#step1", "@type": "CreateAction", "name": "convert",
         "instrument": {"@id": tool_url}, "object": [{"@id": "in.txt"}],
         "result": [{"@id": "mid.txt"}], "agent": {"@id": orcid},
         "startTime": "2024-01-01T09:30:00", "endTime": "2024-01-01T10:00:00"},
        {"@id": "#step2", "@type": "CreateAction", "name": "sort",
         "instrument": {"@id": "#sort"}, "object": [{"@id": "mid.txt"}],
         "result": [{"@id": "out.txt"}], "agent": {"@id": orcid},
         "endTime": "2024-01-01T11:00:00"},
    ]
    return wrroc.to_evi({"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph})


def _prov_load(provjson):
    prov_model = pytest.importorskip("prov.model")
    return prov_model.ProvDocument.deserialize(content=json.dumps(provjson), format="json")


def test_CPM2_export_declares_every_prefix():
    from fairscape_conversion.plugins import cpm
    out = cpm.convert("export", _workflow_evi())
    used = {k.split(":", 1)[0]
            for b in out["bundle"].values()
            for section in ("entity", "activity", "agent") for body in b.get(section, {}).values()
            for k in body if ":" in k}
    assert used <= set(out["prefix"]) | {"prov"}
    _prov_load(out)


def test_CPM3_export_never_writes_urls_as_qualified_names():
    from fairscape_conversion.plugins import cpm
    out = cpm.convert("export", _workflow_evi())
    ids = [k for b in out["bundle"].values()
           for section in ("entity", "activity", "agent") for k in b.get(section, {})]
    assert not [i for i in ids if "://" in i or i.startswith("doi:")]
    _prov_load(out)


def test_CPM23_reference_crate_export_loads_in_prov():
    from fairscape_conversion.plugins import cpm
    _prov_load(cpm.convert("export", cpm.convert("import", str(CPM_INPUT_CRATE))))


def test_CPM4_export_keeps_activity_times_and_agents():
    from fairscape_conversion.plugins import cpm
    evi = _workflow_evi()
    out = cpm.convert("export", evi)
    bundle = next(iter(out["bundle"].values()))
    acts = {body.get("prov:label"): (qn, body) for qn, body in bundle["activity"].items()}
    qn, convert_act = acts["convert"]
    assert convert_act["prov:startTime"].startswith("2024-01-01T09:30:00")
    assert convert_act["prov:endTime"].startswith("2024-01-01T10:00:00")
    assoc = [(r["prov:activity"], r["prov:agent"])
             for r in bundle.get("wasAssociatedWith", {}).values()]
    agent_labels = {aqn: body.get("prov:label") for aqn, body in bundle.get("agent", {}).items()}
    assert any(a == qn and agent_labels.get(ag) == "Josiah Carberry" for a, ag in assoc)
    doc = _prov_load(out)
    assert doc.bundles
