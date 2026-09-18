"""redcap plugin extraction — REDCap exports on disk -> plain records.

The I/O half of the conversion, in the ``plugins/cromwell/extract.py``
mould: everything that opens a file happens here, so the mapping
(``convert("import", records)``) stays a pure function and the golden-file
test stays hermetic.

What REDCap gives you, and what this reads:

* **the data dictionary** — *Project Setup → Data Dictionary → Download*.
  A CSV with eighteen display-named columns ("Variable / Field Name", …).
  The API's ``content=metadata`` export is the same table as JSON with
  snake_case keys (``field_name``, …); both are accepted and normalised to
  the API names, which is what ``parsers.py`` reads.
* **the records export** (optional) — *Data Exports → Export Data → CSV / raw*.
  Only its header row is kept (plus a row count and size). The header is
  what decides which columns the schema describes: a de-identified export
  drops the ``Identifier? = y`` fields, a longitudinal project adds
  ``redcap_event_name``, and the schema must match the file it is attached
  to, not the dictionary in the abstract.

REDCap writes neither its own version nor the project title into either
file, so those are options (``redcap_version``, ``name``). The project name
falls back to the stem REDCap uses when it names downloads
(``<Project>_DataDictionary_<date>.csv`` / ``<Project>_DATA_<date>_<time>.csv``).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from datetime import date

from ...core.arks import DEFAULT_NAAN

# Display header (CSV download) -> API key (content=metadata). The API key is
# the canonical spelling everywhere downstream.
DICTIONARY_COLUMNS = {
    "Variable / Field Name": "field_name",
    "Form Name": "form_name",
    "Section Header": "section_header",
    "Field Type": "field_type",
    "Field Label": "field_label",
    "Choices, Calculations, OR Slider Labels": "select_choices_or_calculations",
    "Field Note": "field_note",
    "Text Validation Type OR Show Slider Number": "text_validation_type_or_show_slider_number",
    "Text Validation Min": "text_validation_min",
    "Text Validation Max": "text_validation_max",
    "Identifier?": "identifier",
    "Branching Logic (Show field only if...)": "branching_logic",
    "Required Field?": "required_field",
    "Custom Alignment": "custom_alignment",
    "Question Number (surveys only)": "question_number",
    "Matrix Group Name": "matrix_group_name",
    "Matrix Ranking?": "matrix_ranking",
    "Field Annotation": "field_annotation",
}
API_KEYS = tuple(DICTIONARY_COLUMNS.values())

_DOWNLOAD_NAME = re.compile(r"^(?P<project>.+?)_(DataDictionary|DATA|LABELS)_\d{4}-\d{2}-\d{2}")


def _canonical_key(header: str) -> str:
    """A dictionary column name in either spelling -> its API key."""
    text = (header or "").strip().lstrip("﻿")
    if text in DICTIONARY_COLUMNS:
        return DICTIONARY_COLUMNS[text]
    if text in API_KEYS:
        return text
    # tolerate case / whitespace drift in a hand-edited dictionary
    folded = text.lower()
    for display, key in DICTIONARY_COLUMNS.items():
        if folded in (display.lower(), key):
            return key
    return text


def read_dictionary(path) -> list[dict]:
    """The data dictionary as a list of field dicts keyed by API name."""
    path = str(path)
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8-sig") as f:
            rows = json.load(f)
        if not isinstance(rows, list):
            raise ValueError(f"{path}: expected the API metadata export (a JSON list)")
    else:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    fields = []
    for row in rows:
        field = {key: "" for key in API_KEYS}
        for header, value in row.items():
            field[_canonical_key(header)] = (value or "").strip() if isinstance(value, str) else (value or "")
        if not field["field_name"]:
            continue
        fields.append(field)
    if not fields:
        raise ValueError(f"{path}: no fields found — is this a REDCap data dictionary?")
    return fields


def read_records_header(path) -> dict:
    """Header row, row count and size of a records export CSV."""
    path = str(path)
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            columns = [c.strip() for c in next(reader)]
        except StopIteration:
            raise ValueError(f"{path}: empty records export")
        rows = sum(1 for _ in reader)
    return {"columns": columns, "rows": rows, "size": os.path.getsize(path)}


def dictionary_key(fields: list[dict]) -> str:
    """A stable digest of what the dictionary *defines* — the ARK source.

    Field name, form, type, validation and choices, in order. Labels,
    notes and layout columns are left out so a wording edit does not
    re-mint every identifier, while adding or retyping a field does.
    """
    parts = ["|".join((f["field_name"], f["form_name"], f["field_type"],
                       f["text_validation_type_or_show_slider_number"],
                       f["select_choices_or_calculations"]))
             for f in fields]
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()


def project_name_from(path) -> str | None:
    """``MyStudy_DataDictionary_2026-01-12.csv`` -> ``MyStudy``."""
    stem = os.path.splitext(os.path.basename(str(path)))[0]
    match = _DOWNLOAD_NAME.match(stem)
    return match.group("project").replace("_", " ") if match else None


def _relative(path, crate_dir) -> str:
    if crate_dir:
        try:
            return os.path.relpath(path, crate_dir)
        except ValueError:          # different drive on Windows
            pass
    return os.path.basename(str(path))


def extract(dictionary, records=None, *, naan=DEFAULT_NAAN, name=None,
            description=None, author=None, keywords=None, license=None,
            version="1.0", date_published=None, redcap_version=None,
            labels=False, crate_dir=None) -> dict:
    """Read the REDCap files and return the plain records ``convert`` maps.

    ``dictionary`` is the data dictionary path (CSV download or API JSON);
    ``records`` the optional records export CSV. ``labels`` says the export
    was made with *labels* rather than raw codes, which changes the type
    and pattern of every choice column.
    """
    fields = read_dictionary(dictionary)
    project = (name or project_name_from(records or "") or project_name_from(dictionary)
               or os.path.splitext(os.path.basename(str(dictionary)))[0])
    forms = []
    for f in fields:
        if f["form_name"] and f["form_name"] not in forms:
            forms.append(f["form_name"])

    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    out = {
        "settings": {
            "naan": naan,
            "name": project,
            "description": description or (
                f"REDCap project '{project}': its data dictionary "
                f"({len(fields)} fields over {len(forms)} form(s)) as an EVI "
                "schema" + (", with the exported records" if records else "")),
            "author": author or "",
            "keywords": keywords or ["redcap", "data dictionary", "survey"],
            "license": license or "https://spdx.org/licenses/CC-BY-4.0",
            "version": version,
            "date_published": date_published or date.today().isoformat(),
        },
        "project": {
            "name": project,
            "dictionary_key": dictionary_key(fields),
            "labels": bool(labels),
            "redcap_version": redcap_version or "",
        },
        "fields": fields,
        "dictionary_file": {
            "file": os.path.basename(str(dictionary)),
            "local_path": _relative(dictionary, crate_dir),
            "format": "application/json" if str(dictionary).lower().endswith(".json") else "text/csv",
            "size": os.path.getsize(dictionary),
        },
        "records": None,
    }
    if records:
        header = read_records_header(records)
        out["records"] = {
            "file": os.path.basename(str(records)),
            "local_path": _relative(records, crate_dir),
            **header,
        }
    return out
