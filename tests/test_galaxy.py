"""galaxy plugin tests: golden file (the green-field pattern from
NEW-PLUGIN.md) plus the other input shapes.

``input-store/`` is the model store Galaxy 23.0 wrote for the Workflow Run
RO-Crate spec's ``galaxy-collection-wf-crate`` example (its
ro-crate-metadata.json removed: this plugin reads Galaxy's own files);
``input.json`` is what ``extract`` makes of it, ``golden.json`` the reviewed
conversion. The invocation carries its own timestamps, so the conversion is
deterministic.
"""

import json
import tarfile
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "galaxy"
STORE = PLUGIN_DIR / "input-store"


def _load(name):
    with open(PLUGIN_DIR / name) as f:
        return json.load(f)


def _by_kind(crate, kind):
    return [n for n in crate["@graph"] if kind in str(n.get("@type")) and "ROCrate" not in str(n.get("@type"))]


def _named(crate, prefix):
    return next(n for n in crate["@graph"] if str(n.get("name", "")).startswith(prefix))


def test_galaxy_import_matches_golden():
    from fairscape_conversion.plugins import galaxy
    assert galaxy.convert("import", _load("input.json")) == _load("golden.json")


def test_extract_reproduces_input_json():
    from fairscape_conversion.plugins.galaxy import extract as x
    assert x.extract(STORE, author="Example Researcher", crate_dir=STORE) == _load("input.json")


def test_arks_are_deterministic():
    from fairscape_conversion.plugins import galaxy
    a = galaxy.convert("import", _load("input.json"))
    b = galaxy.convert("import", _load("input.json"))
    assert [n["@id"] for n in a["@graph"]] == [n["@id"] for n in b["@graph"]]


def test_invocation_is_a_computation_over_its_jobs():
    crate = _load("golden.json")
    run = _named(crate, "Galaxy invocation of")
    jobs = [n for n in _by_kind(crate, "Computation") if n is not run]
    in_run = [j for j in jobs if j.get("isPartOf") == [{"@id": run["@id"]}]]
    uploads = [j for j in jobs if j["name"].startswith("upload")]
    assert len(jobs) == 6 and len(in_run) == 3 and len(uploads) == 3
    assert run["parameter"] == ["num_lines_param=2"]
    assert len(run["usedDataset"]) == 2            # the two input collections
    assert len(run["generated"]) == 3              # the declared workflow outputs
    software = {n["@id"]: n["name"] for n in _by_kind(crate, "Software")}
    assert sorted(software[s["@id"]] for s in run["usedSoftware"]) == ["Galaxy", "collection_workflow"]
    head = _named(crate, "head (step 5")
    assert head["command"].startswith("head -n 2")
    assert head["parameter"] == ["lineNum=2"] and head["exitCode"] == 0 and head["status"] == "ok"


def test_history_copies_collapse_and_uploads_generate_the_inputs():
    """Nine HDAs, five underlying files; each 'hello' copy is one node whose
    generatedBy is the upload job, so the graph reaches the raw input."""
    crate = _load("golden.json")
    datasets = [n for n in _by_kind(crate, "Dataset") if not n.get("hasPart")]
    assert [d["name"] for d in datasets] == ["Concatenate dataset collection (for test workflows) on data 5, data 4, and data 3",
                                             "Select first on data 7", "hello", "world", "universe"]
    hello = _named(crate, "hello")
    assert "3 history copies" in hello["description"]
    uploads = {n["@id"] for n in _by_kind(crate, "Computation") if n["name"].startswith("upload")}
    assert hello["generatedBy"]["@id"] in uploads
    assert hello["format"] == "text/plain" and hello["additionalType"] == "txt"


def test_collections_have_parts_and_a_producing_job():
    crate = _load("golden.json")
    merged = _named(crate, "data 31, data 30, and others (merged)")
    assert len(merged["hasPart"]) == 3 and merged["additionalType"] == "galaxy:list"
    merge_job = _named(crate, "__MERGE_COLLECTION__ (step 3")
    assert merged["generatedBy"] == {"@id": merge_job["@id"]}
    assert {"@id": merged["@id"]} in merge_job["generated"]
    members = {p["@id"] for p in merged["hasPart"]}
    assert members <= {g["@id"] for g in merge_job["generated"]}
    inputs = _named(crate, "hello_world")
    assert "generatedBy" not in inputs and len(inputs["hasPart"]) == 2


def test_tools_and_toolshed_urls():
    from fairscape_conversion.plugins.galaxy.parsers import tool_url, tool_short_name
    crate = _load("golden.json")
    names = sorted(n["name"] for n in _by_kind(crate, "Software"))
    assert names == ["Galaxy", "__DATA_FETCH__", "__MERGE_COLLECTION__", "cat_collection",
                     "collection_workflow", "head"]
    galaxy = next(n for n in _by_kind(crate, "Software") if n["name"] == "Galaxy")
    assert galaxy["version"] == "23.0"
    tid = "toolshed.g2.bx.psu.edu/repos/iuc/bwa_mem2/bwa_mem2/2.2.1+galaxy0"
    assert tool_short_name(tid) == "bwa_mem2"
    assert tool_url(tid, None, None) == "https://toolshed.g2.bx.psu.edu/view/iuc/bwa_mem2/2.2.1+galaxy0"


def test_a_bare_ga_file_gives_software_only():
    from fairscape_conversion.plugins import galaxy
    crate = galaxy.convert("import", STORE / "workflows" / "2154bc930d1891d1.ga", validate=True)
    assert not _by_kind(crate, "Computation") and not _by_kind(crate, "Dataset")
    software = sorted(n["name"] for n in _by_kind(crate, "Software"))
    assert software == ["Galaxy", "__MERGE_COLLECTION__", "cat_collection", "collection_workflow", "head"]
    wf = next(n for n in _by_kind(crate, "Software") if n["name"] == "collection_workflow")
    assert wf["license"] == "MIT" and wf["author"] == "Paul"
    assert "3 tool step(s)" in wf["description"]
    root = crate["@graph"][1]
    assert root["description"] == "Test workflow with a collection"


def test_an_export_archive_is_unpacked(tmp_path):
    from fairscape_conversion.plugins import galaxy
    archive = tmp_path / "invocation-export.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(STORE, arcname="export")
    crate = galaxy.convert("import", archive, author="Example Researcher")
    golden = _load("golden.json")
    assert [n["@id"] for n in crate["@graph"]] == [n["@id"] for n in golden["@graph"]]


def test_not_a_galaxy_export_is_rejected(tmp_path):
    from fairscape_conversion.plugins.galaxy import extract as x
    with pytest.raises(FileNotFoundError):
        x.find_store(tmp_path)
    (tmp_path / "wf.ga").write_text('{"name": "x"}')
    with pytest.raises(ValueError):
        x.read_ga(tmp_path / "wf.ga")
    with pytest.raises(ValueError):
        x.extract("https://usegalaxy.example")           # needs api_key + invocation_id


def test_galaxy_export_unsupported():
    from fairscape_conversion.plugins import galaxy
    with pytest.raises(NotImplementedError):
        galaxy.convert("export", _load("golden.json"))
