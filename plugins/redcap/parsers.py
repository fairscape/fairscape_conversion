"""redcap plugin parsers — the algorithm half of the mapping.

Every parser has the kernel signature ``fn(value, rule, ctx) -> value | None``
(``None`` = set nothing). The one real algorithm here is ``columns``: turning
the dictionary's field list into the columns a REDCap *record export* has,
because a field and a column are not the same thing —

* a ``checkbox`` field becomes one ``field___code`` column per choice;
* every form gets a trailing ``<form>_complete`` status column;
* a ``descriptive`` field is display text and has no column at all;
* a longitudinal / repeating project's export opens with
  ``redcap_event_name`` / ``redcap_repeat_instrument`` / ``redcap_repeat_instance``,
  which the dictionary never mentions.

The REDCap-type -> JSON-Schema-type table is data (``field_types.csv``);
``choice_type`` is the one rule that cannot be a table row because it looks
at the field's own choice codes.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from ...core.parsers import scalar

HERE = Path(__file__).resolve().parent

JSON_SCHEMA = "https://json-schema.org/draft/2020-12/schema"

# Columns REDCap prepends to an export that the dictionary does not define.
EXPORT_BOOKKEEPING = {
    "redcap_event_name": ("string", "Longitudinal event (unique event name) this row belongs to"),
    "redcap_repeat_instrument": ("string", "Repeating instrument this row is an instance of (blank for non-repeating rows)"),
    "redcap_repeat_instance": ("integer", "Instance number of the repeating instrument or event"),
    "redcap_data_access_group": ("string", "Data access group the record belongs to"),
    "redcap_survey_identifier": ("string", "Survey participant identifier"),
}

_INT = re.compile(r"^-?\d+$")
_TAG = re.compile(r"<[^>]+>")


# ---- field_types.csv --------------------------------------------------------

def load_field_types() -> list[dict]:
    with open(HERE / "field_types.csv", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("field_type")]


FIELD_TYPES = load_field_types()


def validation_family(validation: str) -> str:
    """``number_2dp`` -> ``number``; ``datetime_seconds_mdy`` -> ``datetime_seconds``;
    ``date_dmy`` -> ``date``. The family is what field_types.csv keys on."""
    v = (validation or "").strip().lower()
    if not v:
        return ""
    if v.startswith("datetime_seconds"):
        return "datetime_seconds"
    if v.startswith("datetime"):
        return "datetime"
    if v.startswith("date"):
        return "date"
    if v.startswith("number"):
        return "number"
    if v.startswith("integer"):
        return "integer"
    if v.startswith("time"):
        return "time"
    return v


def type_rule(field_type: str, validation: str) -> dict:
    """The field_types.csv row for a field: exact (type, family) first, then
    the type's ``*`` row, then a string."""
    family = validation_family(validation)
    for row in FIELD_TYPES:
        if row["field_type"] == field_type and row["validation"] == family:
            return row
    for row in FIELD_TYPES:
        if row["field_type"] == field_type and row["validation"] == "*":
            return row
    return {"json_type": "string", "pattern": "", "source_type": ""}


# ---- choices ----------------------------------------------------------------

def parse_choices(spec: str) -> list[tuple[str, str]]:
    """``"1, Female | 2, Male"`` -> ``[("1", "Female"), ("2", "Male")]``.

    A label may itself contain a comma, so only the first one splits. A
    spec with no comma anywhere (slider labels, a calc expression) is not a
    choice list and yields nothing.
    """
    out = []
    for part in (spec or "").split("|"):
        part = part.strip()
        if not part or "," not in part:
            continue
        code, label = part.split(",", 1)
        out.append((code.strip(), label.strip()))
    return out


def checkbox_column(field_name: str, code: str) -> str:
    """REDCap's export column for one checkbox choice: ``field___code``, code
    lower-cased with a leading minus and any other non-alphanumerics as ``_``."""
    return f"{field_name}___{re.sub(r'[^a-z0-9]', '_', code.lower())}"


def choice_constraints(choices, labels: bool) -> dict:
    """type + enum (+ pattern for strings) for a radio/dropdown column.

    A raw export writes the code, so the column is an integer when every
    code is one, else a string; a labels export writes the label text.
    ``enum`` is the JSON-Schema statement of the allowed set; frictionless
    only enforces ``pattern`` and only on strings, so strings get both.
    """
    if labels:
        values = [label for _, label in choices]
        return {"type": "string", "enum": values, "pattern": _exact(values)}
    codes = [code for code, _ in choices]
    if codes and all(_INT.match(c) for c in codes):
        return {"type": "integer", "enum": [int(c) for c in codes]}
    return {"type": "string", "enum": codes, "pattern": _exact(codes)}


def _exact(values) -> str:
    return "^(" + "|".join(re.escape(v) for v in values) + ")$" if values else ""


def _number(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return int(text) if _INT.match(text) else float(text)
    except ValueError:
        return None


def clean_label(text: str) -> str:
    """Field labels are HTML in REDCap; the description is plain text."""
    return re.sub(r"\s+", " ", _TAG.sub(" ", text or "")).strip()


# ---- columns ----------------------------------------------------------------

def field_columns(field: dict, labels: bool) -> list[tuple[str, dict]]:
    """The export column(s) one dictionary field produces, as (name, Property)."""
    ftype = field["field_type"]
    if ftype == "descriptive":
        return []
    name = field["field_name"]
    label = clean_label(field["field_label"]) or f"{name} ({field['form_name']})"
    rule = type_rule(ftype, field["text_validation_type_or_show_slider_number"])
    base = {
        "description": label,
        "type": rule["json_type"],
        "form": field["form_name"],
        "fieldType": ftype,
    }
    if rule.get("pattern"):
        base["pattern"] = rule["pattern"]
    if rule.get("source_type"):
        base["source-type"] = rule["source_type"]
    validation = field["text_validation_type_or_show_slider_number"]
    if validation and ftype in ("text", "slider"):
        base["validation"] = validation
    if field["section_header"]:
        base["sectionHeader"] = clean_label(field["section_header"])
    if field["field_note"]:
        base["fieldNote"] = clean_label(field["field_note"])
    if field["branching_logic"]:
        base["branchingLogic"] = field["branching_logic"]
    if field["identifier"].lower() == "y":
        base["phiIdentifier"] = True
    if field["required_field"].lower() == "y":
        base["requiredField"] = True
    if ftype == "calc":
        base["calculation"] = field["select_choices_or_calculations"]
    if base["type"] in ("integer", "number"):
        low, high = _number(field["text_validation_min"]), _number(field["text_validation_max"])
        if low is not None:
            base["minimum"] = low
        if high is not None:
            base["maximum"] = high
        if ftype == "slider":
            base.setdefault("minimum", 0)
            base.setdefault("maximum", 100)

    choices = parse_choices(field["select_choices_or_calculations"])
    if ftype == "checkbox":
        out = []
        for code, choice_label in choices:
            prop = dict(base)
            prop["description"] = f"{label} — {choice_label} (1 = checked)"
            prop.update({"minimum": 0, "maximum": 1, "enum": [0, 1]})
            prop["choice"] = {"code": code, "label": choice_label}
            out.append((checkbox_column(name, code), prop))
        return out
    if ftype in ("radio", "dropdown") and choices:
        base.pop("pattern", None)
        base.update(choice_constraints(choices, labels))
        base["choices"] = {code: choice_label for code, choice_label in choices}
    return [(name, base)]


def form_status_column(form: str) -> tuple[str, dict]:
    return f"{form}_complete", {
        "description": f"REDCap form status for '{form}': 0 = Incomplete, 1 = Unverified, 2 = Complete",
        "type": "integer",
        "minimum": 0,
        "maximum": 2,
        "enum": [0, 1, 2],
        "form": form,
        "fieldType": "form_status",
    }


def columns(src: dict) -> dict[str, dict]:
    """Every column of the record export, in export order, as Properties.

    Without a records header this is the dictionary's own order (form by
    form, each closed by its status column). With one, the header is the
    truth: it fixes the order, drops what the export left out (identifier
    fields in a de-identified export), and adds what the dictionary cannot
    know (event/instance bookkeeping, or a column nobody documented).
    """
    labels = src["project"].get("labels", False)
    fields = src["fields"]
    known: dict[str, dict] = {}
    forms: list[str] = []
    for field in fields:
        form = field["form_name"]
        if form and form not in forms:
            forms.append(form)
        for col, prop in field_columns(field, labels):
            known.setdefault(col, prop)
    for form in forms:
        col, prop = form_status_column(form)
        known.setdefault(col, prop)

    records = src.get("records")
    if not records:
        order = list(known)
    else:
        order = records["columns"]
    out = {}
    for i, col in enumerate(order):
        if col in known:
            prop = dict(known[col])
        elif col in EXPORT_BOOKKEEPING:
            json_type, description = EXPORT_BOOKKEEPING[col]
            prop = {"description": description, "type": json_type, "fieldType": "export_bookkeeping"}
        else:
            prop = {"description": f"Column '{col}' of the export; not in the data dictionary",
                    "type": "string", "fieldType": "undocumented"}
        prop = {"description": prop.pop("description"), "index": i, "type": prop.pop("type"), **prop}
        out[col] = prop
    return out


def _columns(ctx) -> dict[str, dict]:
    """The columns, computed once per conversion."""
    if "columns" not in ctx.extras:
        ctx.extras["columns"] = columns(ctx.source)
    return ctx.extras["columns"]


# ---- Schema -----------------------------------------------------------------

def schema_name(value, rule, ctx):
    return f"Schema for REDCap project '{value}' record export"


def schema_description(value, rule, ctx):
    src = ctx.source
    cols = _columns(ctx)
    forms = [f for f in dict.fromkeys(f["form_name"] for f in src["fields"]) if f]
    n_fields = sum(1 for f in src["fields"] if f["field_type"] != "descriptive")
    text = (f"Columns of a REDCap {'labels' if src['project'].get('labels') else 'raw'} "
            f"record export for project '{value}': {n_fields} fields on "
            f"{len(forms)} form(s) become {len(cols)} columns (checkbox fields expand "
            f"to one column per choice; each form adds a _complete status column). "
            "Derived from the project's data dictionary.")
    phi = [c for c, p in cols.items() if p.get("phiIdentifier")]
    if phi:
        text += f" {len(phi)} column(s) are flagged as identifiers in REDCap: {', '.join(phi)}."
    return text


def json_schema_ref(value, rule, ctx):
    return {"@id": JSON_SCHEMA}


def schema_properties(value, rule, ctx):
    return _columns(ctx)


def schema_required(value, rule, ctx):
    cols = _columns(ctx)
    first = ctx.source["fields"][0]["field_name"] if ctx.source["fields"] else None
    return [c for c, p in cols.items() if p.get("requiredField") or c == first] or None


def additional_properties(value, rule, ctx):
    return not ctx.source.get("records")


def constant_object(value, rule, ctx):
    return "object"


def constant_comma(value, rule, ctx):
    return ","


def constant_true(value, rule, ctx):
    return True


def form_list(value, rule, ctx):
    forms = [f for f in dict.fromkeys(f["form_name"] for f in ctx.source["fields"]) if f]
    return forms or None


def identifier_fields(value, rule, ctx):
    return [c for c, p in _columns(ctx).items() if p.get("phiIdentifier")] or None


# ---- Datasets ---------------------------------------------------------------

def crate_author(value, rule, ctx):
    return ctx.source["settings"].get("author") or None


def crate_date(value, rule, ctx):
    return ctx.source["settings"]["date_published"]


def crate_keywords(value, rule, ctx):
    return list(ctx.source["settings"].get("keywords") or []) or None


def dictionary_description(value, rule, ctx):
    src = ctx.source
    forms = [f for f in dict.fromkeys(f["form_name"] for f in src["fields"]) if f]
    return (f"REDCap data dictionary for project '{src['project']['name']}': "
            f"{len(src['fields'])} fields on {len(forms)} form(s) "
            f"({', '.join(forms)}), as downloaded from REDCap")


def records_description(value, rule, ctx):
    src = ctx.source
    rec = src["records"]
    return (f"Records exported from REDCap project '{src['project']['name']}' "
            f"({rec['rows']} row(s), {len(rec['columns'])} columns, "
            f"{'labels' if src['project'].get('labels') else 'raw codes'})")


def records_access(value, rule, ctx):
    phi = [c for c, p in _columns(ctx).items() if p.get("phiIdentifier")]
    if not phi:
        return None
    return ("Contains columns REDCap flags as identifiers: " + ", ".join(phi)
            + ". Handle under the project's IRB and data use terms.")


def constant_csv(value, rule, ctx):
    return "text/csv"


def schema_ref(value, rule, ctx):
    return {"@id": ctx.extras["guid_map"]["project"]}


def export_ref(value, rule, ctx):
    return {"@id": ctx.extras["guid_map"]["export"]}


# ---- Computation / Software --------------------------------------------------

def export_name(value, rule, ctx):
    return f"REDCap export from project '{ctx.source['project']['name']}'"


def export_description(value, rule, ctx):
    src = ctx.source
    what = "the data dictionary"
    if src.get("records"):
        what += " and a record export"
    return (f"Download of {what} from REDCap project '{src['project']['name']}' "
            "(REDCap's Data Dictionary and Data Exports pages, or the API)")


def used_software(value, rule, ctx):
    return [{"@id": ctx.extras["guid_map"]["redcap"]}]


def export_generated(value, rule, ctx):
    ids = [ctx.extras["guid_map"]["dictionary"]]
    if ctx.source.get("records"):
        ids.append(ctx.extras["guid_map"]["records"])
    return [{"@id": i} for i in ids]


def constant_redcap(value, rule, ctx):
    return "REDCap"


def redcap_description(value, rule, ctx):
    return ("Research Electronic Data Capture (REDCap), the web application "
            "that hosted the project and produced its data dictionary and record exports")


def constant_redcap_url(value, rule, ctx):
    return "https://projectredcap.org"


def constant_vanderbilt(value, rule, ctx):
    return "Vanderbilt University"


def constant_web_app(value, rule, ctx):
    return "application/x-web-application"


IMPORT_PARSERS = {
    "scalar": scalar,
    "identity": lambda v, r, c: v if v not in (None, "", [], {}) else None,
    "schema_name": schema_name,
    "schema_description": schema_description,
    "json_schema_ref": json_schema_ref,
    "schema_properties": schema_properties,
    "schema_required": schema_required,
    "additional_properties": additional_properties,
    "constant_object": constant_object,
    "constant_comma": constant_comma,
    "constant_true": constant_true,
    "form_list": form_list,
    "identifier_fields": identifier_fields,
    "crate_author": crate_author,
    "crate_date": crate_date,
    "crate_keywords": crate_keywords,
    "dictionary_description": dictionary_description,
    "records_description": records_description,
    "records_access": records_access,
    "constant_csv": constant_csv,
    "schema_ref": schema_ref,
    "export_ref": export_ref,
    "export_name": export_name,
    "export_description": export_description,
    "used_software": used_software,
    "export_generated": export_generated,
    "constant_redcap": constant_redcap,
    "redcap_description": redcap_description,
    "constant_redcap_url": constant_redcap_url,
    "constant_vanderbilt": constant_vanderbilt,
    "constant_web_app": constant_web_app,
}
