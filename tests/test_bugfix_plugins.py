"""Regression tests for the plugin bugs in bugs.md (2026-10-12 bug hunt):
CW1, CW2 (cromwell), M1 (mlflow), C2M2-3, C2M2-4 (c2m2), F1 (frictionless)
and G1 / F6 (galaxy / frictionless author fallback).

Every fixture is built here (tmp_path) or derived from a plugin's own shipped
example, so the tests run anywhere the package does.
"""

import copy
import csv
import json
import os
import shutil
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
EVI = "https://w3id.org/EVI#"


def _nodes(crate):
    return {n["@id"]: n for n in crate["@graph"]}


def _ids(refs):
    if refs is None:
        return []
    if isinstance(refs, dict):
        refs = [refs]
    return [r["@id"] for r in refs]


def _is(node, typ):
    return typ in str(node.get("@type"))


def _validate(crate):
    from fairscape_models.rocrate import ROCrateV1_2
    ROCrateV1_2.model_validate(copy.deepcopy(crate))


# ---- cromwell ------------------------------------------------------------------

def _touch(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return str(path)


def _cromwell_metadata(root, calls, outputs=None):
    return {
        "id": "0d3c5d0e-0000-4000-8000-000000000000",
        "workflowName": "main",
        "workflowRoot": str(root),
        "status": "Succeeded",
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-01-01T00:10:00Z",
        "submittedFiles": {"workflow": "version 1.0\nworkflow main {}\n", "inputs": "{}"},
        "workflowProcessingEvents": [{"cromwellVersion": "92"}],
        "inputs": {},
        "outputs": outputs or {},
        "calls": calls,
    }


def _attempt(shard=-1, **kw):
    return {"shardIndex": shard, "attempt": 1, "executionStatus": "Done",
            "start": "2026-01-01T00:01:00Z", "end": "2026-01-01T00:02:00Z", **kw}


def test_CW1_scattered_subworkflow_keeps_every_inner_shard(tmp_path):
    """A subworkflow scattered over 3 shards whose inner call has no File
    outputs: all 3 inner calls must become Computations, each reading its
    own part file."""
    from fairscape_conversion.plugins import cromwell
    from fairscape_conversion.plugins.cromwell.extract import extract

    root = tmp_path / "cromwell-executions" / "main" / "0d3c5d0e-0000-4000-8000-000000000000"
    parts = [_touch(root / "call-split" / "execution" / f"part_{i}.txt", f"line {i}\n")
             for i in range(3)]
    shards = []
    for i, part in enumerate(parts):
        sub = {"workflowName": "subwf", "calls": {"subwf.count_lines": [_attempt(
            inputs={"f": part}, outputs={"n": 1},
            callRoot=str(root / "call-sw" / f"shard-{i}" / "sub" / "call-count_lines"))]}}
        shards.append({"shardIndex": i, "attempt": 1, "subWorkflowMetadata": sub})
    meta = _cromwell_metadata(root, {"main.sw": shards})
    mpath = tmp_path / "metadata.json"
    mpath.write_text(json.dumps(meta))

    records = extract(str(mpath), date_published="2026-01-01T00:00:00Z")
    assert sum(j["task"].endswith("count_lines") for j in records["jobs"]) == 3
    crate = cromwell.convert("import", records)
    nodes = _nodes(crate)
    count = [n for n in crate["@graph"]
             if _is(n, "Computation") and "count_lines" in n.get("name", "")]
    assert len(count) == 3, f"expected 3 count_lines Computations, got {len(count)}"
    read = {nodes[i]["name"] for n in count for i in _ids(n.get("usedDataset"))}
    assert read == {"part_0.txt", "part_1.txt", "part_2.txt"}


def test_CW2_uuid_named_glob_outputs_stay_distinct(tmp_path):
    """Two glob outputs whose long names differ only in a trailing UUID must
    be two Datasets, both listed in the job's generated."""
    from fairscape_conversion.plugins import cromwell
    from fairscape_conversion.plugins.cromwell.extract import extract

    root = tmp_path / "cromwell-executions" / "main" / "0d3c5d0e-0000-4000-8000-000000000000"
    exe = root / "call-uuid_long" / "execution"
    outs = [_touch(exe / f"aligned_reads_for_sample_cohort_batch_0001_{u}.txt", f"file {k}\n")
            for k, u in enumerate(["2b1f6c1e-9a77-4b0e-8f3e-3c1d2e4f5a6b",
                                   "7c9e8d2a-1b3c-4d5e-9f60-718293a4b5c6"])]
    calls = {"main.uuid_long": [_attempt(inputs={}, outputs={"outs": outs},
                                         callRoot=str(root / "call-uuid_long"))]}
    mpath = tmp_path / "metadata.json"
    mpath.write_text(json.dumps(_cromwell_metadata(root, calls)))

    crate = cromwell.convert("import", extract(str(mpath), date_published="2026-01-01T00:00:00Z"))
    job = next(n for n in crate["@graph"] if _is(n, "Computation") and n["name"] == "uuid_long")
    generated = _ids(job["generated"])
    assert len(set(generated)) == 2, f"generated collapsed: {generated}"
    datasets = [n for n in crate["@graph"]
                if _is(n, "Dataset") and n.get("name", "").startswith("aligned_reads")]
    assert len(datasets) == 2


def test_C3_cromwell_rerun_gets_a_new_root_ark(tmp_path):
    """Two runs of the same WDL under the same name are different runs, so
    their crate roots and run Computations must not share an ARK."""
    from fairscape_conversion.plugins import cromwell
    from fairscape_conversion.plugins.cromwell.extract import extract

    roots = []
    for k, wf_id in enumerate(["0d3c5d0e-0000-4000-8000-000000000000",
                               "1e4d6e1f-0000-4000-8000-000000000001"]):
        root = tmp_path / f"r{k}" / "cromwell-executions" / "main" / wf_id
        out = _touch(root / "call-t" / "execution" / "out.txt", f"run {k}\n")
        calls = {"main.t": [_attempt(inputs={}, outputs={"o": out},
                                     callRoot=str(root / "call-t"))]}
        meta = _cromwell_metadata(root, calls)
        meta["id"] = wf_id
        mpath = tmp_path / f"metadata{k}.json"
        mpath.write_text(json.dumps(meta))
        crate = cromwell.convert("import", extract(str(mpath), date_published="2026-01-01T00:00:00Z"))
        roots.append(crate["@graph"][0]["about"]["@id"])
    assert roots[0] != roots[1], f"both runs minted root {roots[0]}"


# ---- mlflow --------------------------------------------------------------------

def _mlflow_case(tmp_path, producer_start, producer_end, artifact_text, source_text):
    """A consumer run (10:00-10:05) logs a local dataset x.csv; another run
    logged an artifact also called x.csv."""
    from fairscape_conversion.plugins.mlflow.extract import _alias_dataset_inputs

    src = tmp_path / "data" / "x.csv"
    _touch(src, source_text)
    art = tmp_path / "crate" / "exporter-aaaaaaaa" / "x.csv"
    _touch(art, artifact_text)
    runs = [
        {"run_id": "consumer", "start_time": "2026-01-01T10:00:00+00:00",
         "end_time": "2026-01-01T10:05:00+00:00",
         "dataset_inputs": [{"key": "x@d1", "context": "training"}]},
        {"run_id": "exporter", "start_time": producer_start, "end_time": producer_end,
         "dataset_inputs": []},
    ]
    datasets = {"x@d1": {"key": "x@d1", "source_type": "local",
                         "source_uri": "file://" + str(src)}}
    files = {"exporter:x.csv": {"key": "exporter:x.csv", "path": "x.csv",
                                "run_id": "exporter", "size": len(artifact_text),
                                "locator": "localPath", "locator_value": str(art)}}
    _alias_dataset_inputs(runs, datasets, files)
    return runs[0]["dataset_inputs"][0].get("file_key")


def test_M1_dataset_input_not_aliased_to_later_run_artifact(tmp_path):
    """The exporter ran an hour after the consumer finished; its artifact
    cannot be what the consumer read."""
    key = _mlflow_case(tmp_path, "2026-01-01T11:00:00+00:00", "2026-01-01T11:01:00+00:00",
                       "a,b\n1,2\n", "a,b\n1,2\n")
    assert key is None, "consumer's input aliased to an artifact logged after it ran"


def test_M1_dataset_input_not_aliased_when_md5_differs(tmp_path):
    """Same name and size, earlier producer, different content: not the same file."""
    key = _mlflow_case(tmp_path, "2026-01-01T09:00:00+00:00", "2026-01-01T09:01:00+00:00",
                       "a,b\n1,2\n", "a,b\n3,4\n")
    assert key is None, "aliased to an artifact whose content differs"


def test_M1_dataset_input_still_aliased_to_earlier_identical_artifact(tmp_path):
    """Control: an earlier run's identical artifact is still linked."""
    key = _mlflow_case(tmp_path, "2026-01-01T09:00:00+00:00", "2026-01-01T09:01:00+00:00",
                       "a,b\n1,2\n", "a,b\n1,2\n")
    assert key == "exporter:x.csv"


# ---- c2m2 ----------------------------------------------------------------------

C2M2_INPUT = PLUGINS / "c2m2" / "input-datapackage"


def _write_tsv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def test_C2M2_3_same_local_id_in_two_namespaces_stays_distinct(tmp_path):
    from fairscape_conversion.plugins import c2m2

    dp = tmp_path / "dp"
    shutil.copytree(C2M2_INPUT, dp)
    _write_tsv(dp / "id_namespace.tsv", ["id", "name"], [["nsA", "A"], ["nsB", "B"]])
    _write_tsv(dp / "project.tsv", ["id_namespace", "local_id", "name"],
               [["nsA", "proj1", "A project"], ["nsB", "proj1", "B project"]])
    _write_tsv(dp / "subject.tsv", ["id_namespace", "local_id"], [["nsA", "s1"], ["nsB", "s1"]])
    _write_tsv(dp / "biosample.tsv",
               ["id_namespace", "local_id", "project_id_namespace", "project_local_id"],
               [["nsA", "b1", "nsA", "proj1"], ["nsB", "b1", "nsB", "proj1"]])
    _write_tsv(dp / "biosample_from_subject.tsv",
               ["biosample_id_namespace", "biosample_local_id",
                "subject_id_namespace", "subject_local_id"],
               [["nsA", "b1", "nsA", "s1"], ["nsB", "b1", "nsB", "s1"]])
    _write_tsv(dp / "file_describes_biosample.tsv",
               ["file_id_namespace", "file_local_id", "biosample_id_namespace",
                "biosample_local_id"], [])
    _write_tsv(dp / "file.tsv",
               ["id_namespace", "local_id", "project_id_namespace", "project_local_id",
                "persistent_id", "size_in_bytes", "sha256", "filename", "file_format",
                "mime_type", "access_url"],
               [["nsA", "f1", "nsA", "proj1", "", "10", "", "a.fastq", "", "", ""],
                ["nsB", "f1", "nsB", "proj1", "", "20", "", "brain.fastq", "", "", ""]])
    desc = json.loads((dp / "C2M2_datapackage.json").read_text())
    desc["resources"].append({
        "profile": "tabular-data-resource", "name": "biosample_from_subject",
        "path": "biosample_from_subject.tsv",
        "schema": {"fields": [{"name": n, "type": "string"} for n in
                              ("biosample_id_namespace", "biosample_local_id",
                               "subject_id_namespace", "subject_local_id")],
                   "primaryKey": ["biosample_id_namespace", "biosample_local_id",
                                  "subject_id_namespace", "subject_local_id"]}})
    (dp / "C2M2_datapackage.json").write_text(json.dumps(desc))

    crate = c2m2.convert("import", dp, output_path=tmp_path / "out",
                         date_published="2026-01-01")
    graph = crate["@graph"]
    subjects = [n for n in graph if _is(n, "Patient") or n.get("additionalType") == "Patient"
                or "-subject/" in n["@id"]]
    biosamples = [n for n in graph if "-biosample/" in n["@id"]]
    files = [n for n in graph if "-file/" in n["@id"]]
    assert len(subjects) == 2, [n["@id"] for n in subjects]
    assert len(biosamples) == 2, [n["@id"] for n in biosamples]
    assert {n.get("name") for n in files} >= {"a.fastq", "brain.fastq"}
    # each biosample derives from its own namespace's subject
    for b in biosamples:
        ns = "nsa" if "nsa" in b["@id"].lower() else "nsb"
        derived = _ids(b.get("prov:wasDerivedFrom"))
        assert derived and all(ns in d.lower() for d in derived), (b["@id"], derived)


def test_C2M2_4_conversion_does_not_claim_to_generate_dcc_files(tmp_path):
    from fairscape_conversion.plugins import c2m2

    crate = c2m2.convert("import", C2M2_INPUT, output_path=tmp_path / "out",
                         date_published="2026-01-01")
    nodes = _nodes(crate)
    comp = next(n for n in crate["@graph"] if n["@id"].endswith("-conversion"))
    generated = set(_ids(comp.get("generated")))
    used = set(_ids(comp.get("usedDataset")))
    # file.tsv rows: one minted ARK, one reusing its persistent_id ARK
    file_rows = {i for i in nodes if "-file/" in i or i == "ark:99999/data-bin"}
    assert file_rows, "fixture has file rows"
    assert not generated & file_rows, f"conversion claims to generate {generated & file_rows}"
    tables = {i for i, n in nodes.items() if n.get("cfde:c2m2Table")}
    assert tables and tables <= used, "the TSVs the conversion read are its inputs"
    root = next(n for n in crate["@graph"] if n.get("@id") == comp["isPartOf"][0]["@id"])
    assert file_rows <= set(_ids(root.get("hasPart"))), "file rows remain crate members"
    # generated / generatedBy agree both ways
    for gid in generated:
        assert comp["@id"] in _ids(nodes[gid].get("generatedBy")), gid
    for i, n in nodes.items():
        if comp["@id"] in _ids(n.get("generatedBy")):
            assert i in generated, i


# ---- frictionless --------------------------------------------------------------

def _frictionless_pkg(tmp_path, schema, dialect=None):
    pkg = tmp_path / "pkg"
    (pkg / "data").mkdir(parents=True)
    (pkg / "data" / "t.csv").write_text("id;name\n1;a\n2;b\n")
    resource = {"name": "t", "path": "data/t.csv", "schema": schema}
    if dialect is not None:
        resource["dialect"] = dialect
    (pkg / "datapackage.json").write_text(json.dumps(
        {"name": "p", "contributors": [{"title": "X", "role": "author"}],
         "resources": [resource]}))
    return pkg


def _write_schema(pkg):
    (pkg / "schema.json").write_text(json.dumps(
        {"fields": [{"name": "id", "type": "integer"}, {"name": "name", "type": "string"}],
         "primaryKey": "id"}))
    (pkg / "dialect.json").write_text(json.dumps({"delimiter": ";"}))


def test_F1_schema_and_dialect_given_as_local_paths_are_loaded(tmp_path):
    from fairscape_conversion.plugins import frictionless

    pkg = _frictionless_pkg(tmp_path, "schema.json", "dialect.json")
    _write_schema(pkg)
    crate = frictionless.convert("import", str(pkg), crate_dir=str(pkg))
    schema = next(n for n in crate["@graph"] if _is(n, "Schema"))
    assert set(schema["properties"]) == {"id", "name"}
    assert schema["separator"] == ";"
    dataset = next(n for n in crate["@graph"] if n.get("alternateName") == "t")
    assert dataset["evi:Schema"] == {"@id": schema["@id"]}


def test_F1_schema_given_as_url_is_kept_as_a_reference(tmp_path, monkeypatch):
    from fairscape_conversion.plugins import frictionless
    import urllib.request

    def no_network(*a, **k):
        raise AssertionError("import must not fetch remote schemas")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)

    url = "https://example.org/schemas/t.schema.json"
    pkg = _frictionless_pkg(tmp_path, url, "https://example.org/dialect.json")
    crate = frictionless.convert("import", str(pkg), crate_dir=str(pkg))
    dataset = next(n for n in crate["@graph"] if n.get("alternateName") == "t")
    assert dataset["evi:Schema"] == {"@id": url}


# ---- author fallbacks ----------------------------------------------------------

def test_G1_galaxy_without_author_writes_a_valid_crate():
    from fairscape_conversion.plugins import galaxy

    records = json.loads((PLUGINS / "galaxy" / "input.json").read_text())
    records["settings"]["author"] = ""
    records["workflow"].pop("creators", None)
    crate = galaxy.convert("import", records)
    for n in crate["@graph"]:
        if _is(n, "Computation"):
            assert n.get("runBy") == "Unknown", n["@id"]
    _validate(crate)


def test_F6_frictionless_without_contributors_writes_a_valid_crate():
    from fairscape_conversion.plugins import frictionless

    records = json.loads((PLUGINS / "frictionless" / "input.json").read_text())
    records["settings"]["author"] = ""
    records["package"]["contributors"] = None
    crate = frictionless.convert("import", records)
    for n in crate["@graph"][1:]:
        if _is(n, "Dataset"):
            assert n.get("author") == "Unknown", n["@id"]
    _validate(crate)
