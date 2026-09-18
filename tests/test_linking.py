"""Linked crates: a converted crate reuses an upstream crate's ids for what it
only consumed (``core/linking.py``).

Everything runs on crates written into ``tmp_path`` — an *upstream* crate that
generated a file and a directory, and a *consumer* crate that used them — so
the tests need no real workflow run. The last test drives the pass through a
real conversion (the mlflow plugin) to prove the ``linked_crates`` option is
wired through ``PluginBase.import_``.
"""

import json
import os
from pathlib import Path

import pytest

EVI = "https://w3id.org/EVI#"
UP_ROOT = "ark:59853/rocrate-upstream-1111111"
UP_RUN = "ark:59853/computation-upstream-run-2222222"
UP_FILE = "ark:59853/dataset-table-tsv-3333333"
UP_DIR = "ark:59853/dataset-outdir-4444444"
UP_SUM = "ark:59853/dataset-summed-txt-5555555"


def _write(path: Path, crate: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(crate, indent=1))
    return path


@pytest.fixture
def upstream(tmp_path):
    """A workflow crate: one run generated table.tsv, an output directory
    holding nested.txt, and summed.txt (declared with an md5, no contentUrl)."""
    d = tmp_path / "upstream" / "results"
    d.mkdir(parents=True)
    (d / "table.tsv").write_text("a\tb\n1\t2\n")
    (d / "outdir").mkdir()
    (d / "outdir" / "nested.txt").write_text("nested\n")
    crate = {"@context": {}, "@graph": [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "about": {"@id": UP_ROOT}},
        {"@id": UP_ROOT, "@type": ["Dataset", EVI + "ROCrate"], "name": "Upstream run",
         "description": "the producer", "author": "Up Stream", "keywords": ["up"],
         "hasPart": [{"@id": UP_RUN}, {"@id": UP_FILE}, {"@id": UP_DIR}, {"@id": UP_SUM}],
         EVI + "outputs": [{"@id": UP_FILE}]},
        {"@id": UP_RUN, "@type": ["prov:Activity", EVI + "Computation"], "name": "RUN",
         "generated": [{"@id": UP_FILE}, {"@id": UP_DIR}, {"@id": UP_SUM}]},
        {"@id": UP_FILE, "@type": ["prov:Entity", EVI + "Dataset"], "name": "table.tsv",
         "description": "File 'table.tsv' produced by RUN", "author": "Up Stream",
         "datePublished": "2026-01-01", "keywords": ["up"], "format": "text/tab-separated-values",
         "contentUrl": "table.tsv", "generatedBy": [{"@id": UP_RUN}],
         "evi:Schema": {"@id": "ark:59853/schema-upstream-only"}},
        {"@id": UP_DIR, "@type": ["prov:Entity", EVI + "Dataset"], "name": "outdir",
         "description": "Directory 'outdir' produced by RUN", "contentUrl": "outdir",
         "generatedBy": [{"@id": UP_RUN}]},
        {"@id": UP_SUM, "@type": ["prov:Entity", EVI + "Dataset"], "name": "summed.txt",
         "description": "declared by checksum only", "md5": "0123456789ABCDEF0123456789abcdef",
         "generatedBy": [{"@id": UP_RUN}]},
    ]}
    _write(d / "ro-crate-metadata.json", crate)
    return d


def _consumer(up_dir: Path, own_dir: Path) -> dict:
    """A crate that used table.tsv (absolute localPath), outdir/nested.txt
    (absolute path inside the directory), a checksum-only file, and one input
    nothing upstream knows about; plus its own output."""
    c_in = "ark:59853/dataset-table-tsv-aaaaaaa"
    c_in2 = "ark:59853/dataset-table-tsv-copy-a2a2a2a"
    c_nested = "ark:59853/dataset-nested-txt-bbbbbbb"
    c_sum = "ark:59853/dataset-summed-txt-eeeeeee"
    c_other = "ark:59853/dataset-other-csv-ccccccc"
    c_run = "ark:59853/computation-analysis-ddddddd"
    c_out = "ark:59853/dataset-result-json-fffffff"
    root = "ark:59853/rocrate-consumer-9999999"
    return {"@context": {}, "@graph": [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "about": {"@id": root}},
        {"@id": root, "@type": ["Dataset", EVI + "ROCrate"], "name": "Consumer",
         "hasPart": [{"@id": c_in}, {"@id": c_in2}, {"@id": c_nested}, {"@id": c_sum},
                     {"@id": c_other}, {"@id": c_run}, {"@id": c_out}],
         EVI + "inputs": [{"@id": c_in}, {"@id": c_in2}, {"@id": c_nested}, {"@id": c_sum}, {"@id": c_other}]},
        {"@id": c_in, "@type": ["prov:Entity", EVI + "Dataset"], "name": "table",
         "description": "Dataset 'table' logged as an MLflow run input", "digest": "8f9eb48c",
         "localPath": str(up_dir / "table.tsv"), "generatedBy": [],
         "evi:Schema": {"@id": "ark:59853/schema-consumer-colspec"}},
        {"@id": c_in2, "@type": ["prov:Entity", EVI + "Dataset"], "name": "table.tsv",
         "description": "the same file logged twice", "contentUrl": "file://" + str(up_dir / "table.tsv"),
         "generatedBy": []},
        {"@id": c_nested, "@type": ["prov:Entity", EVI + "Dataset"], "name": "nested.txt",
         "localPath": str(up_dir / "outdir" / "nested.txt"), "generatedBy": []},
        {"@id": c_sum, "@type": ["prov:Entity", EVI + "Dataset"], "name": "summed.txt",
         "localPath": "/somewhere/else/summed.txt", "md5": "0123456789abcdef0123456789ABCDEF",
         "generatedBy": []},
        {"@id": c_other, "@type": ["prov:Entity", EVI + "Dataset"], "name": "other.csv",
         "contentUrl": "other.csv", "generatedBy": []},
        {"@id": c_run, "@type": ["prov:Activity", EVI + "Computation"], "name": "analysis",
         "usedDataset": [{"@id": c_in}, {"@id": c_in2}, {"@id": c_nested}, {"@id": c_sum}, {"@id": c_other}],
         "generated": [{"@id": c_out}]},
        {"@id": c_out, "@type": ["prov:Entity", EVI + "Dataset"], "name": "result.json",
         "contentUrl": "result.json", "generatedBy": [{"@id": c_run}]},
    ]}


def _by_id(crate):
    return {n["@id"]: n for n in crate["@graph"]}


def test_path_match_reuses_upstream_id_and_rewrites_every_reference(upstream, tmp_path):
    from fairscape_conversion.core.linking import link_crate

    own = tmp_path / "consumer"
    crate = _consumer(upstream, own)
    report = link_crate(crate, [upstream], crate_dir=str(own))
    nodes = _by_id(crate)

    assert {m.method for m in report.matches} == {"path", "md5", "directory"}
    assert "ark:59853/dataset-table-tsv-aaaaaaa" not in nodes
    stub = nodes[UP_FILE]
    # upstream identity and description, no provenance, absolute location
    assert stub["@type"] == ["prov:Entity", EVI + "Dataset"]
    assert stub["description"] == "File 'table.tsv' produced by RUN"
    assert "generatedBy" not in stub and "contentUrl" not in stub
    assert stub["localPath"] == str(upstream / "table.tsv")
    assert stub["isPartOf"] == [{"@id": UP_ROOT}]
    # the consumer's own extras survive; the upstream's schema pointer does not
    assert stub["digest"] == "8f9eb48c"
    assert stub["evi:Schema"] == {"@id": "ark:59853/schema-consumer-colspec"}
    # every reference now names the upstream id, exactly once
    run = nodes["ark:59853/computation-analysis-ddddddd"]
    used = [r["@id"] for r in run["usedDataset"]]
    assert used.count(UP_FILE) == 1 and "ark:59853/dataset-table-tsv-aaaaaaa" not in used
    root = nodes["ark:59853/rocrate-consumer-9999999"]
    assert {r["@id"] for r in root["hasPart"]} >= {UP_FILE, UP_SUM}
    assert UP_FILE in [r["@id"] for r in root[EVI + "inputs"]]
    # no consumer id leaks anywhere in the document
    text = json.dumps(crate)
    assert "aaaaaaa" not in text and "a2a2a2a" not in text and "eeeeeee" not in text


def test_two_consumer_nodes_for_one_upstream_file_fold_into_one_stub(upstream, tmp_path):
    from fairscape_conversion.core.linking import link_crate

    crate = _consumer(upstream, tmp_path / "consumer")
    link_crate(crate, [upstream], crate_dir=str(tmp_path / "consumer"))
    ids = [n["@id"] for n in crate["@graph"]]
    assert ids.count(UP_FILE) == 1
    assert "ark:59853/dataset-table-tsv-copy-a2a2a2a" not in ids


def test_md5_match_when_paths_differ(upstream, tmp_path):
    from fairscape_conversion.core.linking import link_crate

    crate = _consumer(upstream, tmp_path / "consumer")
    report = link_crate(crate, [upstream], crate_dir=str(tmp_path / "consumer"))
    m = next(m for m in report.matches if m.method == "md5")
    assert m.new_id == UP_SUM
    assert _by_id(crate)[UP_SUM]["isPartOf"] == [{"@id": UP_ROOT}]


def test_directory_match_keeps_own_id_and_points_at_the_directory(upstream, tmp_path):
    from fairscape_conversion.core.linking import link_crate

    crate = _consumer(upstream, tmp_path / "consumer")
    link_crate(crate, [upstream], crate_dir=str(tmp_path / "consumer"))
    nodes = _by_id(crate)
    nested = nodes["ark:59853/dataset-nested-txt-bbbbbbb"]
    assert nested["isPartOf"] == [{"@id": UP_DIR}]
    # the directory itself is stubbed in, pointing at the upstream crate
    assert nodes[UP_DIR]["isPartOf"] == [{"@id": UP_ROOT}]
    assert "generatedBy" not in nodes[UP_DIR]


def test_crate_stub_points_at_the_upstream_metadata_file(upstream, tmp_path):
    from fairscape_conversion.core.linking import link_crate

    own = tmp_path / "consumer"
    crate = _consumer(upstream, own)
    link_crate(crate, [upstream], crate_dir=str(own))
    nodes = _by_id(crate)
    stub = nodes[UP_ROOT]
    assert stub["@type"] == ["Dataset", EVI + "ROCrate"]
    assert stub["name"] == "Upstream run"
    assert stub["ro-crate-metadata"] == "../upstream/results/ro-crate-metadata.json"
    assert os.path.normpath(os.path.join(own, stub["ro-crate-metadata"])) == \
        str(upstream / "ro-crate-metadata.json")
    assert stub["localPath"] == str(upstream / "ro-crate-metadata.json")
    # its own hasPart names just the entities this crate took from it
    assert {r["@id"] for r in stub["hasPart"]} == {UP_FILE, UP_SUM, UP_DIR}
    # it is a pointer, not a constituent: never added to hasPart
    root = nodes["ark:59853/rocrate-consumer-9999999"]
    assert UP_ROOT not in [r["@id"] for r in root["hasPart"]]
    # exactly one crate stub even though three inputs came from it
    assert [n["@id"] for n in crate["@graph"]].count(UP_ROOT) == 1


def test_unmatched_inputs_and_own_outputs_are_left_alone(upstream, tmp_path):
    from fairscape_conversion.core.linking import link_crate

    crate = _consumer(upstream, tmp_path / "consumer")
    report = link_crate(crate, [upstream], crate_dir=str(tmp_path / "consumer"))
    assert report.unmatched == ["ark:59853/dataset-other-csv-ccccccc"]
    nodes = _by_id(crate)
    assert nodes["ark:59853/dataset-result-json-fffffff"]["generatedBy"] == \
        [{"@id": "ark:59853/computation-analysis-ddddddd"}]


def test_shared_software_id_is_not_claimed_but_a_shared_dataset_id_is(upstream, tmp_path):
    """Two crates that both describe Snakemake mint the same ARK for it; that
    is not the upstream's entity. A Dataset already carrying the upstream id
    (a run-time helper logged the ARK) is."""
    from fairscape_conversion.core.linking import link_crate

    crate = _consumer(upstream, tmp_path / "consumer")
    crate["@graph"].append({"@id": UP_RUN.replace("computation", "software"),
                            "@type": ["prov:Entity", EVI + "Software"], "name": "engine",
                            "contentUrl": "https://example.org/engine"})
    up = json.loads((upstream / "ro-crate-metadata.json").read_text())
    up["@graph"].append({"@id": UP_RUN.replace("computation", "software"),
                         "@type": ["prov:Entity", EVI + "Software"], "name": "engine",
                         "contentUrl": "https://example.org/engine"})
    up["@graph"].append({"@id": "ark:59853/dataset-shared-7777777",
                         "@type": ["prov:Entity", EVI + "Dataset"], "name": "shared.txt",
                         "contentUrl": "https://example.org/shared.txt",
                         "generatedBy": [{"@id": UP_RUN}]})
    (upstream / "ro-crate-metadata.json").write_text(json.dumps(up))
    crate["@graph"].append({"@id": "ark:59853/dataset-shared-7777777",
                            "@type": ["prov:Entity", EVI + "Dataset"], "name": "shared.txt",
                            "generatedBy": []})
    report = link_crate(crate, [upstream], crate_dir=str(tmp_path / "consumer"))
    methods = {m.new_id: m.method for m in report.matches}
    assert UP_RUN.replace("computation", "software") not in methods
    assert methods["ark:59853/dataset-shared-7777777"] == "id"
    stub = _by_id(crate)["ark:59853/dataset-shared-7777777"]
    assert stub["contentUrl"] == "https://example.org/shared.txt"     # a URL survives
    assert stub["isPartOf"] == [{"@id": UP_ROOT}]


def test_no_linked_crates_is_a_no_op(upstream, tmp_path):
    from fairscape_conversion.core.linking import link_crate

    crate = _consumer(upstream, tmp_path / "consumer")
    before = json.dumps(crate, sort_keys=True)
    report = link_crate(crate, [], crate_dir=str(tmp_path / "consumer"))
    assert not report.matches and json.dumps(crate, sort_keys=True) == before


def test_relative_content_url_resolves_against_crate_dir(upstream, tmp_path):
    """A consumer that recorded the shared file relative to its own folder
    (e.g. a Cromwell crate whose crate_dir contains the upstream results)."""
    from fairscape_conversion.core.linking import link_crate

    own = upstream.parent           # consumer crate written beside results/
    crate = _consumer(upstream, own)
    nodes = _by_id(crate)
    nodes["ark:59853/dataset-table-tsv-aaaaaaa"].pop("localPath")
    nodes["ark:59853/dataset-table-tsv-aaaaaaa"]["contentUrl"] = "results/table.tsv"
    report = link_crate(crate, [upstream], crate_dir=str(own))
    assert any(m.new_id == UP_FILE and m.method == "path" for m in report.matches)


def test_link_crate_file_round_trips_on_disk(upstream, tmp_path):
    from fairscape_conversion.core.linking import link_crate_file

    own = tmp_path / "consumer"
    path = _write(own / "ro-crate-metadata.json", _consumer(upstream, own))
    report = link_crate_file(path, [upstream])
    assert len(report.matches) == 4
    written = json.loads(path.read_text())
    assert UP_FILE in _by_id(written)


def test_linked_crates_option_runs_through_a_real_conversion(upstream, tmp_path):
    """The mlflow plugin, on its shipped records, with one logged dataset
    input re-pointed at the upstream file: ``linked_crates`` is honoured by
    ``PluginBase.import_`` and the crate comes out linked."""
    from fairscape_conversion.plugins.mlflow import convert

    plugin_dir = Path(__file__).resolve().parents[1] / "plugins" / "mlflow"
    records = json.loads((plugin_dir / "input.json").read_text())
    key = next(iter(records["datasets"]))
    records["datasets"][key]["source_type"] = "local"
    records["datasets"][key]["source_uri"] = "file://" + str(upstream / "table.tsv")

    plain = convert("import", json.loads(json.dumps(records)))
    linked = convert("import", records, linked_crates=[str(upstream)],
                     crate_dir=str(tmp_path / "crate"), link_report=True)

    plain_ids = {n["@id"] for n in plain["@graph"]}
    linked_ids = {n["@id"] for n in linked["@graph"]}
    assert UP_FILE not in plain_ids
    assert UP_FILE in linked_ids and UP_ROOT in linked_ids
    assert linked["_linking"][0]["method"] == "path"
    # the run that logged the input now uses the upstream id
    runs = [n for n in linked["@graph"] if "Computation" in str(n.get("@type"))]
    assert any(UP_FILE in [r["@id"] for r in run.get("usedDataset", [])] for run in runs)
    # and the plain conversion recorded where the file came from
    ds = next(n for n in plain["@graph"] if n.get("digest") and n.get("localPath"))
    assert ds["localPath"] == str(upstream / "table.tsv")
