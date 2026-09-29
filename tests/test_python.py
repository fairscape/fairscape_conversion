"""python plugin: golden-file conversion of a run record, plus ``track`` end to end.

``input.json`` is a hand-written run record (fixed paths and times) so the
conversion test stays hermetic; the ``track`` tests run real scripts in a
temporary directory and check the crate they build up.
"""

import builtins
import copy
import json
import pathlib
import textwrap
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "python"


def _load(name):
    with open(PLUGIN_DIR / name) as f:
        return json.load(f)


def _crate(crate_dir):
    return json.loads((Path(crate_dir) / "ro-crate-metadata.json").read_text())


def _by_name(crate, name):
    return [n for n in crate["@graph"] if n.get("name") == name]


def _ids(refs):
    return [r["@id"] for r in refs]


def _script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body))
    return path


# ---- the pure conversion ------------------------------------------------------

def test_python_import_matches_golden():
    from fairscape_conversion.plugins import python as pyrun
    assert pyrun.convert("import", _load("input.json")) == _load("golden.json")


def test_python_arks_are_deterministic():
    from fairscape_conversion.plugins import python as pyrun
    a = pyrun.convert("import", _load("input.json"))
    b = pyrun.convert("import", _load("input.json"))
    assert [n["@id"] for n in a["@graph"]] == [n["@id"] for n in b["@graph"]]


def _validate(crate):
    # conftest puts the sibling checkouts on sys.path, where the fairscape_models
    # repo folder can shadow the installed package; skip rather than fail then.
    rocrate = pytest.importorskip("fairscape_models.rocrate")
    rocrate.ROCrateV1_2.model_validate(copy.deepcopy(crate))


def test_python_golden_validates():
    _validate(_load("golden.json"))


def test_python_export_unsupported():
    from fairscape_conversion.plugins import python as pyrun
    with pytest.raises(NotImplementedError):
        pyrun.convert("export", _load("golden.json"))


# ---- recording ----------------------------------------------------------------

def test_iocapture_records_and_restores(tmp_path):
    from fairscape_conversion.plugins.python.record import IOCapture
    src = tmp_path / "in.txt"
    src.write_text("x")
    original_open, original_read_text = builtins.open, pathlib.Path.read_text
    with IOCapture() as capture:
        open(src).read()
        (tmp_path / "out.txt").write_text("y")
        (tmp_path / "both.txt").write_text("")
        with open(tmp_path / "both.txt", "r+") as f:
            f.write("z")
    assert builtins.open is original_open
    assert pathlib.Path.read_text is original_read_text
    assert capture.inputs == {str(src), str(tmp_path / "both.txt")}
    assert capture.outputs == {str(tmp_path / "out.txt"), str(tmp_path / "both.txt")}


def test_build_record_treats_read_and_written_as_output(tmp_path):
    from fairscape_conversion.plugins.python.record import build_record
    crate = tmp_path / "crate"
    (crate / "data").mkdir(parents=True)
    both = crate / "data" / "tmp.csv"
    both.write_text("a")
    outside = tmp_path / "ref.tsv"
    outside.write_text("b")
    record = build_record(
        code="pass", name="run", script={"locator": "contentUrl", "locator_value": "run.py"},
        inputs=[str(both), str(outside), str(tmp_path / "gone.txt")], outputs=[str(both)],
        crate_dir=crate, starttime="t0", endtime="t1", author="A")
    files = record["files"]
    assert set(files) == {str(both), str(outside)}
    assert files[str(both)] == {"role": "output", "size": 1, "locator": "contentUrl",
                                "locator_value": "data/tmp.csv"}
    assert files[str(outside)]["locator"] == "localPath"


# ---- track --------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "crate" / "data").mkdir(parents=True)
    (tmp_path / "crate" / "data" / "raw.csv").write_text("a,b\n1,2\n")
    _script(tmp_path / "scripts" / "clean.py", """
        import sys
        rows = open(sys.argv[1]).read().splitlines()
        open(sys.argv[2], "w").write("\\n".join(r + ",x" for r in rows))
    """)
    _script(tmp_path / "crate" / "count.py", """
        import pathlib
        n = len(pathlib.Path("crate/data/clean.csv").read_text().splitlines())
        pathlib.Path("crate/data/count.txt").write_text(str(n))
    """)
    return tmp_path


def _track(*argv):
    from fairscape_conversion.core.cli import main
    return main(["track", *argv])


def test_track_builds_a_chained_crate(workspace):
    assert _track("scripts/clean.py", "--crate-dir", "crate", "--author", "Jane Doe",
                  "--", "crate/data/raw.csv", "crate/data/clean.csv") == 0
    assert _track("crate/count.py", "--crate-dir", "crate") == 0

    crate = _crate("crate")
    [clean_run] = _by_name(crate, "Python run of 'clean'")
    [count_run] = _by_name(crate, "Python run of 'count'")
    [clean_csv] = _by_name(crate, "clean.csv")
    [raw_csv] = _by_name(crate, "raw.csv")

    assert _ids(clean_run["usedDataset"]) == [raw_csv["@id"]]
    assert _ids(clean_run["generated"]) == [clean_csv["@id"]]
    # the second run's input IS the first run's output node
    assert _ids(count_run["usedDataset"]) == [clean_csv["@id"]]
    assert clean_run["runBy"] == "Jane Doe"
    assert count_run["runBy"] == "Jane Doe"          # author reused from the crate root

    # code outside the crate is copied in; code inside it is referenced in place
    [clean_sw] = _by_name(crate, "clean.py")
    [count_sw] = _by_name(crate, "count.py")
    assert clean_sw["contentUrl"].startswith("software/clean-")
    assert (workspace / "crate" / clean_sw["contentUrl"]).exists()
    assert count_sw["contentUrl"] == "count.py"

    _validate(crate)


def test_track_rerun_reuses_software_and_adds_a_new_output(workspace):
    args = ("scripts/clean.py", "--crate-dir", "crate", "--",
            "crate/data/raw.csv", "crate/data/clean.csv")
    assert _track(*args) == 0
    assert _track(*args) == 0
    crate = _crate("crate")
    ids = [n["@id"] for n in crate["@graph"]]
    assert len(ids) == len(set(ids))
    assert len(_by_name(crate, "clean.py")) == 1
    assert len(_by_name(crate, "Python run of 'clean'")) == 2
    assert len(_by_name(crate, "clean.csv")) == 2
    assert len(_by_name(crate, "raw.csv")) == 1


def test_track_link_crate(workspace):
    assert _track("scripts/clean.py", "--crate-dir", "crate", "--",
                  "crate/data/raw.csv", "crate/data/clean.csv") == 0
    _script(workspace / "down" / "lines.py", """
        import sys
        open("down/lines.txt", "w").write(str(len(open(sys.argv[1]).readlines())))
    """)
    assert _track("down/lines.py", "--crate-dir", "down", "--link-crate", "crate",
                  "--", "crate/data/clean.csv") == 0

    [upstream_csv] = _by_name(_crate("crate"), "clean.csv")
    down = _crate("down")
    [run] = _by_name(down, "Python run of 'lines'")
    assert _ids(run["usedDataset"]) == [upstream_csv["@id"]]
    [stub] = [n for n in down["@graph"] if n["@id"] == upstream_csv["@id"]]
    assert "generatedBy" not in stub and stub["isPartOf"]


def test_track_start_clean(workspace):
    assert _track("scripts/clean.py", "--crate-dir", "crate", "--",
                  "crate/data/raw.csv", "crate/data/clean.csv") == 0
    assert _track("crate/count.py", "--crate-dir", "crate", "--start-clean") == 0
    crate = _crate("crate")
    assert not _by_name(crate, "Python run of 'clean'")
    assert len(_by_name(crate, "Python run of 'count'")) == 1


def test_track_without_io_writes_nothing(workspace):
    _script(workspace / "noop.py", "print('hi')\n")
    assert _track("noop.py", "--crate-dir", "crate") == 0
    assert not (workspace / "crate" / "ro-crate-metadata.json").exists()


def test_track_failing_script_records_nothing(workspace):
    _script(workspace / "bad.py", "open('crate/data/x.txt', 'w').write('x')\nraise ValueError('boom')\n")
    assert _track("bad.py", "--crate-dir", "crate") == 1
    assert not (workspace / "crate" / "ro-crate-metadata.json").exists()


def test_track_nonzero_exit_is_recorded(workspace):
    _script(workspace / "partial.py", """
        import sys
        open("crate/data/partial.txt", "w").write("x")
        sys.exit(3)
    """)
    assert _track("partial.py", "--crate-dir", "crate") == 3
    [run] = _by_name(_crate("crate"), "Python run of 'partial'")
    assert run["exitCode"] == "3"
