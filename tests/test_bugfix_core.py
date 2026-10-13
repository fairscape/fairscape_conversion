"""Regression tests for the core / linking / track bugs in ``bugs.md``
(C1-C6, P1, P5, the engine's silent duplicate-id drop, and validation by
default). Each test is named after the bug it pins and builds its own inputs
in ``tmp_path``.
"""

import json
import os
import warnings
from pathlib import Path

import pytest

EVI = "https://w3id.org/EVI#"
ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _graph(crate):
    return {n["@id"]: n for n in crate["@graph"]}


def _ids(value):
    if value is None:
        return []
    value = value if isinstance(value, list) else [value]
    return [v["@id"] if isinstance(v, dict) else v for v in value]


def _types(node):
    t = node.get("@type") or []
    return t if isinstance(t, list) else [t]


def _write_crate(directory: Path, crate: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ro-crate-metadata.json"
    path.write_text(json.dumps(crate, indent=1))
    return path


def _sm_records(workdir: Path, name: str, jobs, files, *, start="2026-10-01T00:00:00",
                rules=None):
    """A Snakemake reporter record for a project rooted at ``workdir``; every
    listed file is written with content unique to this project."""
    for f in files:
        (workdir / f).parent.mkdir(parents=True, exist_ok=True)
        if not (workdir / f).exists():
            (workdir / f).write_text(f"{workdir.name}:{f}\n")
    (workdir / "Snakefile").write_text("# snakefile\n")
    return {
        "settings": {"naan": "59853", "name": name, "description": name + " run",
                     "author": "x", "keywords": ["x"], "license": "CC-BY-4.0",
                     "version": "1", "date_published": "2026-10-01"},
        "run": {"name": name, "snakefile": "Snakefile",
                "snakefile_key": str(workdir / "Snakefile"), "engine_version": "9.0",
                "starttime": start, "endtime": start},
        "jobs": jobs,
        "rules": rules or {j["rule"]: {"source": "cat {input} > {output}", "language": "bash"}
                           for j in jobs},
        "files": {f: {"size": 5, "parent": None, "is_dir": False, "locator": "contentUrl",
                      "locator_value": f} for f in files},
        "configfiles": [], "schemas": {},
    }


def _sm_job(rule, inputs, outputs, start="2026-10-01T00:00:00"):
    return {"rule": rule, "wildcards": {}, "shellcmd": "cat", "params": [],
            "inputs": inputs, "outputs": outputs, "starttime": start, "endtime": start}


def _sm_convert(records, **options):
    from fairscape_conversion.plugins import snakemake
    return snakemake.convert("import", json.loads(json.dumps(records)), **options)


def _by_name(crate, name):
    return [n for n in crate["@graph"] if n.get("name") == name]


# ---------------------------------------------------------------------------
# engine: duplicate @id
# ---------------------------------------------------------------------------

def test_engine_duplicate_id_with_different_content_warns():
    """First-writer-wins dedup dropped the second node silently (the shared
    root cause of C1, C3, CW1, CW2, D4, C2M2-3)."""
    from fairscape_conversion.plugins import example

    source = {"memos": [{"id": "m1", "title": "first"}, {"id": "m1", "title": "second"}]}
    with pytest.warns(UserWarning, match="m1"):
        out = example.convert("import", source)
    assert [n["name"] for n in out["@graph"]] == ["first"]     # first writer still wins


def test_engine_identical_duplicate_is_silent():
    from fairscape_conversion.plugins import example

    source = {"memos": [{"id": "m1", "title": "same"}, {"id": "m1", "title": "same"}]}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        example.convert("import", source)


# ---------------------------------------------------------------------------
# C1: unrelated projects' files share an ARK and get linked
# ---------------------------------------------------------------------------

@pytest.fixture
def two_projects(tmp_path):
    a, b = tmp_path / "projA", tmp_path / "projB"
    a.mkdir(), b.mkdir()
    rec_a = _sm_records(a, "Project A", [_sm_job("make_table", ["data/raw.txt"], ["results/table.tsv"])],
                        ["data/raw.txt", "results/table.tsv"])
    rec_b = _sm_records(b, "Project B", [_sm_job("summarise", ["results/table.tsv"], ["out/summary.txt"])],
                        ["results/table.tsv", "out/summary.txt"])
    crate_a = _sm_convert(rec_a)
    _write_crate(a, crate_a)
    return a, b, rec_a, rec_b, crate_a


def test_C1_unrelated_projects_get_distinct_file_arks(two_projects):
    a, b, rec_a, rec_b, crate_a = two_projects
    crate_b = _sm_convert(rec_b)
    id_a = _by_name(crate_a, "table.tsv")[0]["@id"]
    id_b = _by_name(crate_b, "table.tsv")[0]["@id"]
    assert id_a != id_b


def test_C1_linking_does_not_claim_an_unrelated_projects_file(two_projects):
    a, b, rec_a, rec_b, crate_a = two_projects
    id_a = _by_name(crate_a, "table.tsv")[0]["@id"]
    crate_b = _sm_convert(rec_b, linked_crates=[str(a)], crate_dir=str(b), link_report=True)
    assert all(m["new_id"] != id_a for m in crate_b["_linking"])
    assert id_a not in _graph(crate_b)


def _hand_crate(root_id, nodes):
    return {"@context": {}, "@graph": [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "about": {"@id": root_id}},
        {"@id": root_id, "@type": ["Dataset", EVI + "ROCrate"], "name": root_id,
         "description": "hand-built crate", "keywords": ["x"], "version": "1",
         "author": "x", "license": "CC-BY-4.0",
         "hasPart": [{"@id": n["@id"]} for n in nodes]},
        *nodes]}


def test_C1_id_match_rejected_when_paths_disagree(tmp_path):
    """Same ARK, but each side's locator names a different existing file."""
    from fairscape_conversion.core.linking import link_crate

    shared = "ark:59853/dataset-table-tsv-0c3dbf6"
    (tmp_path / "up").mkdir()
    (tmp_path / "up" / "table.tsv").write_text("upstream\n")
    (tmp_path / "me").mkdir()
    (tmp_path / "me" / "table.tsv").write_text("mine\n")
    up = _hand_crate("ark:59853/rocrate-up-1", [
        {"@id": "ark:59853/computation-up-2", "@type": ["prov:Activity", EVI + "Computation"],
         "generated": [{"@id": shared}]},
        {"@id": shared, "@type": ["prov:Entity", EVI + "Dataset"], "name": "table.tsv",
         "contentUrl": "table.tsv", "generatedBy": [{"@id": "ark:59853/computation-up-2"}]}])
    _write_crate(tmp_path / "up", up)
    me = _hand_crate("ark:59853/rocrate-me-1", [
        {"@id": shared, "@type": ["prov:Entity", EVI + "Dataset"], "name": "table.tsv",
         "contentUrl": "table.tsv", "generatedBy": []}])
    report = link_crate(me, [tmp_path / "up"], crate_dir=str(tmp_path / "me"))
    assert report.matches == []


def test_C1_path_match_rejected_when_md5s_disagree(tmp_path):
    """Same path, but the file was rewritten since the upstream crate saw it."""
    from fairscape_conversion.core.linking import link_crate

    f = tmp_path / "up" / "table.tsv"
    f.parent.mkdir()
    f.write_text("new content\n")
    up = _hand_crate("ark:59853/rocrate-up-1", [
        {"@id": "ark:59853/computation-up-2", "@type": ["prov:Activity", EVI + "Computation"],
         "generated": [{"@id": "ark:59853/dataset-up-3"}]},
        {"@id": "ark:59853/dataset-up-3", "@type": ["prov:Entity", EVI + "Dataset"],
         "name": "table.tsv", "contentUrl": "table.tsv", "md5": "a" * 32,
         "generatedBy": [{"@id": "ark:59853/computation-up-2"}]}])
    _write_crate(tmp_path / "up", up)
    me = _hand_crate("ark:59853/rocrate-me-1", [
        {"@id": "ark:59853/dataset-me-3", "@type": ["prov:Entity", EVI + "Dataset"],
         "name": "table.tsv", "localPath": str(f), "md5": "b" * 32, "generatedBy": []}])
    report = link_crate(me, [tmp_path / "up"])
    assert report.matches == []


# ---------------------------------------------------------------------------
# C2: shared Snakefile path folds the consumer's Software into an upstream rule
# ---------------------------------------------------------------------------

def test_C2_consumer_software_is_not_folded_into_an_upstream_rule(two_projects, tmp_path):
    a, b, rec_a, rec_b, crate_a = two_projects
    second = _sm_records(a, "Project A, second invocation",
                         [_sm_job("finalise", ["results/table.tsv"], ["results/final.txt"],
                                  start="2026-10-02T00:00:00")],
                         ["results/table.tsv", "results/final.txt"], start="2026-10-02T00:00:00")
    consumer = _sm_convert(second, linked_crates=[str(a)], crate_dir=str(a), link_report=True)
    nodes = _graph(consumer)
    finalise_job = next(n for n in consumer["@graph"]
                        if EVI + "Computation" in _types(n) and n.get("name", "").startswith("finalise"))
    used = [nodes[i] for i in _ids(finalise_job.get("usedSoftware")) if i in nodes]
    assert [s["name"] for s in used] == ["finalise"]
    software_names = {n.get("name") for n in consumer["@graph"] if EVI + "Software" in _types(n)}
    assert {"Snakefile", "finalise"} <= software_names
    assert all(m["method"] != "path" or "software" not in m["new_id"]
               for m in consumer["_linking"])


# ---------------------------------------------------------------------------
# C3: a re-run's root collides with the upstream root
# ---------------------------------------------------------------------------

def test_C3_rerun_gets_a_new_root_and_a_pointer_to_the_upstream(two_projects):
    a, b, rec_a, rec_b, crate_a = two_projects
    rerun = json.loads(json.dumps(rec_a))
    rerun["run"]["starttime"] = rerun["run"]["endtime"] = "2026-10-05T00:00:00"
    rerun["jobs"] = [_sm_job("finalise", ["results/table.tsv"], ["results/final.txt"],
                             start="2026-10-05T00:00:00")]
    rerun["rules"] = {"finalise": {"source": "cat", "language": "bash"}}
    rerun["files"] = {f: dict(rec_a["files"]["results/table.tsv"], locator_value=f)
                      for f in ("results/table.tsv", "results/final.txt")}
    (a / "results" / "final.txt").write_text("final\n")
    consumer = _sm_convert(rerun, linked_crates=[str(a)], crate_dir=str(a))
    up_root = crate_a["@graph"][0]["about"]["@id"]
    my_root = consumer["@graph"][0]["about"]["@id"]
    assert my_root != up_root
    pointers = [n for n in consumer["@graph"] if "ro-crate-metadata" in n]
    assert [p["@id"] for p in pointers] == [up_root]
    stub = _by_name(consumer, "table.tsv")[0]
    assert _ids(stub["isPartOf"]) == [up_root]


def test_C3_linking_to_a_crate_with_the_same_root_does_not_self_reference(tmp_path):
    """Defensive: if the roots do collide, no stub may claim to be part of
    the consumer crate itself."""
    from fairscape_conversion.core.linking import link_crate

    root = "ark:59853/rocrate-same-1"
    f = tmp_path / "up" / "t.tsv"
    f.parent.mkdir()
    f.write_text("x\n")
    up = _hand_crate(root, [
        {"@id": "ark:59853/computation-up-2", "@type": ["prov:Activity", EVI + "Computation"],
         "generated": [{"@id": "ark:59853/dataset-up-3"}]},
        {"@id": "ark:59853/dataset-up-3", "@type": ["prov:Entity", EVI + "Dataset"],
         "name": "t.tsv", "contentUrl": "t.tsv",
         "generatedBy": [{"@id": "ark:59853/computation-up-2"}]}])
    _write_crate(tmp_path / "up", up)
    me = _hand_crate(root, [
        {"@id": "ark:59853/dataset-me-3", "@type": ["prov:Entity", EVI + "Dataset"],
         "name": "t.tsv", "localPath": str(f), "generatedBy": []}])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        link_crate(me, [tmp_path / "up"])
    for n in me["@graph"]:
        assert root not in _ids(n.get("isPartOf")), n["@id"]


# ---------------------------------------------------------------------------
# C4: the stub loses the consumer's inverse edges
# ---------------------------------------------------------------------------

def test_C4_stub_keeps_the_consumers_inverse_edges(tmp_path):
    from fairscape_conversion.core.linking import link_crate

    f = tmp_path / "up" / "t.tsv"
    f.parent.mkdir()
    f.write_text("x\n")
    up = _hand_crate("ark:59853/rocrate-up-1", [
        {"@id": "ark:59853/computation-up-2", "@type": ["prov:Activity", EVI + "Computation"],
         "generated": [{"@id": "ark:59853/dataset-up-3"}]},
        {"@id": "ark:59853/dataset-up-3", "@type": ["prov:Entity", EVI + "Dataset"],
         "name": "t.tsv", "contentUrl": "t.tsv",
         "generatedBy": [{"@id": "ark:59853/computation-up-2"}],
         "datasetUsedBy": [{"@id": "ark:59853/computation-up-elsewhere"}]}])
    _write_crate(tmp_path / "up", up)
    run = "ark:59853/computation-me-2"
    me = _hand_crate("ark:59853/rocrate-me-1", [
        {"@id": run, "@type": ["prov:Activity", EVI + "Computation"],
         "usedDataset": [{"@id": "ark:59853/dataset-me-3"}]},
        {"@id": "ark:59853/dataset-me-3", "@type": ["prov:Entity", EVI + "Dataset"],
         "name": "t.tsv", "localPath": str(f), "generatedBy": [],
         "datasetUsedBy": [{"@id": run}]}])
    link_crate(me, [tmp_path / "up"])
    stub = _graph(me)["ark:59853/dataset-up-3"]
    assert _ids(stub.get("datasetUsedBy")) == [run]


# ---------------------------------------------------------------------------
# C5 / C6: linking options on every importer
# ---------------------------------------------------------------------------

@pytest.fixture
def table_upstream(tmp_path):
    """An upstream crate in tmp/up that generated tmp/up/results/table.tsv."""
    d = tmp_path / "up"
    (d / "results").mkdir(parents=True)
    (d / "results" / "table.tsv").write_text("a\tb\n1\t2\n")
    up = _hand_crate("ark:59853/rocrate-up-1", [
        {"@id": "ark:59853/computation-up-2", "@type": ["prov:Activity", EVI + "Computation"],
         "generated": [{"@id": "ark:59853/dataset-table-up"}]},
        {"@id": "ark:59853/dataset-table-up", "@type": ["prov:Entity", EVI + "Dataset"],
         "name": "table.tsv", "contentUrl": "results/table.tsv",
         "generatedBy": [{"@id": "ark:59853/computation-up-2"}]}])
    _write_crate(d, up)
    return d


@pytest.mark.parametrize("plugin", ["wrroc", "d4d"])
def test_C5_link_options_accepted_by_every_importer(plugin, table_upstream, tmp_path):
    import importlib

    mod = importlib.import_module(f"fairscape_conversion.plugins.{plugin}")
    src = json.loads((ROOT / "plugins" / plugin / "input.json").read_text()) \
        if (ROOT / "plugins" / plugin / "input.json").exists() else None
    if src is None:
        import yaml
        src = yaml.safe_load(next((ROOT / "plugins" / plugin).glob("input.y*ml")).read_text())
    crate = mod.convert("import", src, linked_crates=[str(table_upstream)],
                        crate_dir=str(tmp_path), link_report=True)
    assert "_linking" in crate


def test_C6_frictionless_import_keeps_crate_dir_for_linking(table_upstream):
    from fairscape_conversion.plugins import frictionless

    pkg = table_upstream / "results"
    (pkg / "datapackage.json").write_text(json.dumps({
        "name": "pkg", "title": "pkg", "description": "a package",
        "contributors": [{"title": "Jane Doe", "role": "author"}],
        "licenses": [{"name": "CC-BY-4.0", "path": "https://creativecommons.org/licenses/by/4.0/"}],
        "resources": [{"name": "table", "path": "table.tsv", "format": "tsv"}]}))
    crate = frictionless.convert("import", str(pkg), linked_crates=[str(table_upstream)],
                                 crate_dir=str(pkg), link_report=True)
    assert [m["new_id"] for m in crate["_linking"]] == ["ark:59853/dataset-table-up"]


# ---------------------------------------------------------------------------
# validation by default
# ---------------------------------------------------------------------------

def _py_record():
    return json.loads((ROOT / "plugins" / "python" / "input.json").read_text())


def test_validate_by_default_rejects_an_invalid_crate():
    from fairscape_conversion.plugins import python as pyrun

    rec = _py_record()
    rec["settings"]["version"] = None            # root version is required
    with pytest.raises(Exception, match="(?i)version"):
        pyrun.convert("import", rec)


def test_validate_false_opts_out():
    from fairscape_conversion.plugins import python as pyrun

    rec = _py_record()
    rec["settings"]["version"] = None
    crate = pyrun.convert("import", rec, validate=False)
    assert crate["@graph"]


# ---------------------------------------------------------------------------
# P1 / P5: track
# ---------------------------------------------------------------------------

def _track(script: Path, crate: Path):
    from fairscape_conversion.plugins.python.track import track_script
    comp, code = track_script(script, crate_dir=crate)
    assert code == 0
    return comp


def test_P1_read_after_rewrite_uses_the_latest_version(tmp_path):
    crate = tmp_path / "crate"
    crate.mkdir()
    data = crate / "data.csv"
    data.write_text("a\n1\n")
    read = tmp_path / "read_data.py"
    read.write_text(f"open({str(data)!r}).read()\n")
    rewrite = tmp_path / "rewrite_data.py"
    rewrite.write_text(f"open({str(data)!r}, 'w').write('a\\n2\\n')\n")
    _track(read, crate)
    second = _track(rewrite, crate)
    third = _track(read, crate)
    final = json.loads((crate / "ro-crate-metadata.json").read_text())
    third = _graph(final)[third["@id"]]
    assert _ids(third["usedDataset"]) == _ids(second["generated"])


def test_P5a_edited_script_gets_new_software(tmp_path):
    crate = tmp_path / "crate"
    crate.mkdir()
    (crate / "in.txt").write_text("x\n")
    step = crate / "step.py"
    step.write_text(f"open({str(crate / 'in.txt')!r}).read()\n")
    first = _track(step, crate)
    step.write_text(f"# edited\nopen({str(crate / 'in.txt')!r}).read()\n")
    second = _track(step, crate)
    final = _graph(json.loads((crate / "ro-crate-metadata.json").read_text()))
    sw1 = _ids(final[first["@id"]]["usedSoftware"])
    sw2 = _ids(final[second["@id"]]["usedSoftware"])
    assert sw1 != sw2
    assert all(EVI + "Software" in _types(final[s]) for s in sw1 + sw2)


def test_P5b_generated_script_gets_a_software_node(tmp_path):
    crate = tmp_path / "crate"
    crate.mkdir()
    (crate / "in.txt").write_text("x\n")
    writer = tmp_path / "writer.py"
    gen_code = f"open({str(crate / 'in.txt')!r}).read()\\n"
    writer.write_text(f"open({str(crate / 'gen.py')!r}, 'w').write({gen_code!r})\n"
                      .replace("\\\\n", "\\n"))
    _track(writer, crate)
    gen = _track(crate / "gen.py", crate)
    final = _graph(json.loads((crate / "ro-crate-metadata.json").read_text()))
    used = _ids(final[gen["@id"]]["usedSoftware"])
    assert used and all(EVI + "Software" in _types(final[s]) for s in used)
