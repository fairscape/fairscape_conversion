"""redcap plugin golden-file test (the green-field pattern from NEW-PLUGIN.md).

``input-dictionary.csv`` / ``input-records.csv`` are a small public-health
survey project (three forms; text, radio, dropdown, checkbox, yesno, calc,
slider, notes and descriptive fields; three identifier-flagged fields);
``input.json`` is what ``extract`` makes of them, ``golden.json`` the
reviewed conversion. The records carry their own ``date_published``, so
the conversion is fully deterministic.
"""

import json
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "redcap"


def _load(name):
    with open(PLUGIN_DIR / name) as f:
        return json.load(f)


def _schema(crate):
    return next(n for n in crate["@graph"] if "Schema" in str(n.get("@type")))


def test_redcap_import_matches_golden():
    from fairscape_conversion.plugins import redcap
    assert redcap.convert("import", _load("input.json")) == _load("golden.json")


def test_redcap_extract_reproduces_input_json():
    """extract() over the fixture files is what input.json pins (minus the
    machine-dependent paths, which crate_dir pins to the plugin folder)."""
    from fairscape_conversion.plugins.redcap import extract as x
    got = x.extract(PLUGIN_DIR / "input-dictionary.csv", PLUGIN_DIR / "input-records.csv",
                    name="Seasonal respiratory illness survey",
                    author="Example Public Health Group",
                    keywords=["redcap", "survey", "public health", "respiratory"],
                    date_published="2026-01-20", redcap_version="14.5.10",
                    crate_dir=PLUGIN_DIR)
    assert got == _load("input.json")


def test_redcap_arks_are_deterministic_and_ignore_relabelling():
    from fairscape_conversion.plugins import redcap
    from fairscape_conversion.plugins.redcap.extract import dictionary_key
    src = _load("input.json")
    a = redcap.convert("import", src)
    b = redcap.convert("import", src)
    assert [n["@id"] for n in a["@graph"]] == [n["@id"] for n in b["@graph"]]
    relabelled = json.loads(json.dumps(src["fields"]))
    relabelled[3]["field_label"] = "Age (years)"
    assert dictionary_key(relabelled) == dictionary_key(src["fields"])
    retyped = json.loads(json.dumps(src["fields"]))
    retyped[3]["text_validation_type_or_show_slider_number"] = "number"
    assert dictionary_key(retyped) != dictionary_key(src["fields"])


def test_columns_follow_the_dictionary_without_a_records_file():
    from fairscape_conversion.plugins import redcap
    src = _load("input.json")
    src["records"] = None
    crate = redcap.convert("import", src)
    types = [str(n.get("@type")) for n in crate["@graph"]]
    assert sum("Dataset" in t and "ROCrate" not in t for t in types) == 1
    schema = _schema(crate)
    cols = list(schema["properties"])
    assert cols[:2] == ["record_id", "enroll_date"]
    assert "enrollment_complete" in cols and "followup_complete" == cols[-1]
    assert "consent_info" not in cols                       # descriptive: no column
    assert schema["additionalProperties"] is True           # nothing pinned the set
    assert schema["identifierFields"] == ["zip", "dob", "phone"]


def test_records_header_filters_and_orders_the_schema():
    """A de-identified, longitudinal export: identifiers gone, event column added."""
    from fairscape_conversion.plugins import redcap
    src = _load("input.json")
    src["records"]["columns"] = ["record_id", "redcap_event_name", "age", "sex",
                                 "race___3", "enrollment_complete", "mystery"]
    crate = redcap.convert("import", src)
    schema = _schema(crate)
    assert list(schema["properties"]) == src["records"]["columns"]
    assert [p["index"] for p in schema["properties"].values()] == list(range(7))
    assert schema["properties"]["redcap_event_name"]["fieldType"] == "export_bookkeeping"
    assert schema["properties"]["mystery"]["fieldType"] == "undocumented"
    assert "identifierFields" not in schema
    assert schema["additionalProperties"] is False
    records = next(n for n in crate["@graph"] if n.get("name") == "input-records.csv")
    assert "conditionsOfAccess" not in records


def test_labels_export_types_choice_columns_as_strings():
    from fairscape_conversion.plugins import redcap
    src = _load("input.json")
    src["project"]["labels"] = True
    sex = _schema(redcap.convert("import", src))["properties"]["sex"]
    assert sex["type"] == "string"
    assert sex["enum"] == ["Female", "Male", "Intersex", "Prefer not to say"]


def test_schema_is_a_tabular_schema_that_validates_the_export():
    """The whole point: fairscape_models reads the node back as a
    TabularSchema and frictionless accepts the real export against it."""
    models = pytest.importorskip("fairscape_models.schema.registry")
    pytest.importorskip("frictionless")
    schema = models.parse_schema(_schema(_load("golden.json")))
    assert type(schema).__name__ == "TabularSchema"
    assert schema.validate(str(PLUGIN_DIR / "input-records.csv")) == []


def test_api_metadata_json_is_accepted(tmp_path):
    """The API's content=metadata export: same table, snake_case keys, JSON."""
    from fairscape_conversion.plugins.redcap import extract as x
    fields = x.read_dictionary(PLUGIN_DIR / "input-dictionary.csv")
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(fields))
    assert x.read_dictionary(path) == fields


def test_project_name_from_redcap_download_names():
    from fairscape_conversion.plugins.redcap.extract import project_name_from
    assert project_name_from("/x/FluSurvey2026_DataDictionary_2026-01-12.csv") == "FluSurvey2026"
    assert project_name_from("Flu_Survey_DATA_2026-01-12_1530.csv") == "Flu Survey"
    assert project_name_from("dictionary.csv") is None


def test_redcap_export_unsupported():
    from fairscape_conversion.plugins import redcap
    with pytest.raises(NotImplementedError):
        redcap.convert("export", _load("golden.json"))
