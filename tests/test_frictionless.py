"""frictionless plugin tests: golden file (the green-field pattern from
NEW-PLUGIN.md) plus export round trips.

``input-datapackage/`` is a small tabular Data Package (two CSV resources
with Table Schemas — constraints, a composite primary key, a foreign key,
missing-value markers — and one remote PDF resource); ``input.json`` is what
``extract`` makes of it, ``golden.json`` the reviewed conversion. The
package carries its own ``created`` date, so the conversion is deterministic.
"""

import json
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "frictionless"
PACKAGE = PLUGIN_DIR / "input-datapackage"


def _load(name):
    with open(PLUGIN_DIR / name) as f:
        return json.load(f)


def _nodes(crate, kind):
    return [n for n in crate["@graph"] if kind in str(n.get("@type")) and "ROCrate" not in str(n.get("@type"))]


def test_frictionless_import_matches_golden():
    from fairscape_conversion.plugins import frictionless
    assert frictionless.convert("import", _load("input.json")) == _load("golden.json")


def test_extract_reproduces_input_json():
    from fairscape_conversion.plugins.frictionless import extract as x
    assert x.extract(PACKAGE, crate_dir=PACKAGE) == _load("input.json")


def test_a_parsed_descriptor_converts_without_disk():
    """convert() on the descriptor dict alone: no sizes, no descriptor Dataset."""
    from fairscape_conversion.plugins import frictionless
    descriptor = json.loads((PACKAGE / "datapackage.json").read_text())
    crate = frictionless.convert("import", descriptor)
    datasets = _nodes(crate, "Dataset")
    assert [d["name"] for d in datasets] == ["Weekly case counts by county", "County reference",
                                             "Case definitions and methods"]
    assert "contentSize" not in datasets[0]           # nothing on disk to stat
    assert datasets[2]["contentSize"] == "184320"     # but the descriptor's bytes survive
    assert datasets[2]["contentUrl"].startswith("https://")
    assert "localPath" not in datasets[2]
    assert len(_nodes(crate, "Schema")) == 2


def test_arks_follow_the_package_name_and_version():
    from fairscape_conversion.plugins import frictionless
    src = _load("input.json")
    a = frictionless.convert("import", src)
    src["package"]["key"] = "county-respiratory-surveillance-2026@1.3.0"
    b = frictionless.convert("import", src)
    assert [n["@id"] for n in a["@graph"]] != [n["@id"] for n in b["@graph"]]
    assert [n["@id"] for n in a["@graph"]] == \
        [n["@id"] for n in frictionless.convert("import", _load("input.json"))["@graph"]]


def test_table_schema_fields_become_properties():
    schema = next(n for n in _load("golden.json")["@graph"]
                  if "Schema" in str(n.get("@type")) and "cases" in n["name"])
    props = schema["properties"]
    assert list(props) == ["county_fips", "week_start", "cases", "hospitalized",
                           "pathogen", "rate_per_100k", "provisional"]
    assert props["county_fips"]["pattern"] == "^[0-9]{5}$"
    assert props["week_start"] == {"description": "First day of the MMWR week", "index": 1,
                                   "type": "string", "source-type": "date"}
    assert props["pathogen"]["enum"] == ["influenza", "rsv", "covid-19", "other"]
    assert props["rate_per_100k"]["valueURL"].endswith("NCIT_C16345")
    assert schema["required"] == ["county_fips", "week_start", "cases"]
    assert schema["primaryKey"] == ["county_fips", "week_start"]
    assert schema["foreignKeys"][0]["reference"]["resource"] == "counties"
    assert schema["missingValues"] == ["", "NA"]
    assert schema["additionalProperties"] is False


def test_root_takes_the_package_metadata():
    root = _load("golden.json")["@graph"][1]
    assert root["author"] == "Example Public Health Group"        # role=author only
    assert root["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert root["datePublished"] == "2026-03-02"
    assert root["version"] == "1.2.0"
    assert root["url"] == "https://example.org/surveillance/2026"
    assert root["alternateName"] == "county-respiratory-surveillance-2026"


def test_schemas_validate_the_package_files():
    """fairscape_models reads each Schema back as a TabularSchema and the
    package's own CSVs pass, missing-value markers included."""
    models = pytest.importorskip("fairscape_models.schema.registry")
    pytest.importorskip("frictionless")
    for node in _nodes(_load("golden.json"), "Schema"):
        schema = models.parse_schema(node)
        assert type(schema).__name__ == "TabularSchema"
        csv_name = "cases_by_county.csv" if "cases" in node["name"] else "counties.csv"
        assert schema.validate(str(PACKAGE / csv_name)) == []


def test_tsv_and_dialect_pick_the_separator():
    from fairscape_conversion.plugins import frictionless
    src = _load("input.json")
    src["resources"][1]["path"] = "counties.tsv"
    src["resources"][0]["dialect"] = {"delimiter": ";", "header": False}
    crate = frictionless.convert("import", src)
    by_name = {n["name"]: n for n in _nodes(crate, "Schema")}
    assert by_name["Schema for resource 'counties'"]["separator"] == "\t"
    cases = by_name["Schema for resource 'cases_by_county'"]
    assert cases["separator"] == ";" and cases["header"] is False


def test_not_a_datapackage_is_rejected(tmp_path):
    from fairscape_conversion.plugins.frictionless import extract as x
    (tmp_path / "datapackage.json").write_text('{"name": "x"}')
    with pytest.raises(ValueError):
        x.read_descriptor(tmp_path / "datapackage.json")
    with pytest.raises(FileNotFoundError):
        x.find_descriptor(tmp_path / "nowhere")


# --- export -----------------------------------------------------------------

def test_export_round_trips_the_package():
    """import -> export -> import reproduces the crate (bytes aside: the
    first import learned file sizes from disk, the descriptor had none),
    and the exported descriptor keeps names, paths and every schema field."""
    from fairscape_conversion.plugins import frictionless
    original = json.loads((PACKAGE / "datapackage.json").read_text())
    crate = frictionless.convert("import", _load("input.json"))
    package = frictionless.convert("export", crate)

    for want, got in zip(original["resources"], package["resources"]):
        assert got["name"] == want["name"]
        assert got["path"] == want["path"]
        assert got.get("schema", {}).get("fields") == want.get("schema", {}).get("fields")
    assert package["resources"][0]["schema"]["foreignKeys"][0]["reference"]["resource"] == "counties"
    assert package["name"] == original["name"] and package["version"] == original["version"]
    assert package["licenses"] == [{"path": "https://creativecommons.org/licenses/by/4.0/"}]
    assert package["contributors"] == [{"title": "Example Public Health Group", "role": "author"}]
    assert package["profile"] == "data-package"          # the PDF has no schema
    assert "id" not in package                          # the crate's ARK is not a package id

    again = frictionless.convert("import", package)["@graph"]
    first = frictionless.convert("import", original)["@graph"]
    drop = lambda nodes: [{k: v for k, v in n.items() if k != "contentSize"} for n in nodes]
    assert drop(again) == drop(first)


def test_export_of_another_plugins_crate():
    """A crate the redcap plugin made: its records Dataset + Schema become a
    tabular resource; the dictionary file a plain resource; the export
    Computation and REDCap Software are left out."""
    from fairscape_conversion.plugins import frictionless
    crate = json.loads((PLUGIN_DIR.parent / "redcap" / "golden.json").read_text())
    package = frictionless.convert("export", crate)
    by_name = {r["name"]: r for r in package["resources"]}
    assert set(by_name) == {"input-dictionary.csv", "input-records.csv"}
    records = by_name["input-records.csv"]
    schema = next(n for n in crate["@graph"] if "Schema" in str(n.get("@type")))
    assert [f["name"] for f in records["schema"]["fields"]] == list(schema["properties"])
    sex = next(f for f in records["schema"]["fields"] if f["name"] == "sex")
    assert sex["type"] == "integer" and sex["constraints"]["enum"] == [1, 2, 3, 99]
    assert sex["choices"] == schema["properties"]["sex"]["choices"]     # custom keys survive
    assert next(f for f in records["schema"]["fields"] if f["name"] == "record_id")["constraints"]["required"]
    assert package["title"] == "Seasonal respiratory illness survey"
