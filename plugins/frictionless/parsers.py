"""frictionless plugin parsers — the algorithm half of the mapping.

Kernel signature throughout: ``fn(value, rule, ctx) -> value | None``. The
substantive algorithm is ``field_property``: one Table Schema field -> one
EVI ``Property``. Types come from ``field_types.csv``; constraints map to
JSON-Schema keywords (``pattern``, ``minimum``, ``maximum``, ``enum``,
``minLength``, ``maxLength``); ``rdfType`` (the column's semantic type)
becomes ``valueURL``; anything else on the field is kept as-is.
"""

from __future__ import annotations

import csv
import mimetypes
import os
from pathlib import Path

from ...core.parsers import drop, encoding_format_of, scalar

HERE = Path(__file__).resolve().parent
JSON_SCHEMA = "https://json-schema.org/draft/2020-12/schema"


def load_field_types() -> dict[str, dict]:
    with open(HERE / "field_types.csv", newline="") as f:
        return {r["frictionless_type"]: r for r in csv.DictReader(f) if r.get("frictionless_type")}


FIELD_TYPES = load_field_types()

# constraint -> Property keyword (same name unless listed)
CONSTRAINT_KEYS = {"pattern": "pattern", "minimum": "minimum", "maximum": "maximum",
                   "enum": "enum", "minLength": "minLength", "maxLength": "maxLength",
                   "unique": "unique"}
FIELD_KEYS_HANDLED = {"name", "type", "description", "constraints", "rdfType", "format", "title"}


# ---- helpers ----------------------------------------------------------------

def _package(ctx):
    return ctx.source["package"]


def _settings(ctx):
    return ctx.source["settings"]


def _contributors(ctx, role=None):
    people = _package(ctx).get("contributors") or []
    picked = [c for c in people if not role or c.get("role") == role]
    return [c.get("title") or c.get("email") for c in picked if c.get("title") or c.get("email")]


def _license_of(licenses):
    if not licenses:
        return None
    first = licenses[0] if isinstance(licenses, list) else licenses
    if isinstance(first, str):
        return first
    return first.get("path") or first.get("name")


def field_property(field: dict, index: int, resource_name: str) -> dict:
    """One Table Schema field -> one EVI Property (a plain dict)."""
    ftype = field.get("type") or "any"
    rule = FIELD_TYPES.get(ftype) or FIELD_TYPES["any"]
    prop = {
        "description": field.get("description") or field.get("title")
                       or f"Column '{field.get('name')}' of resource '{resource_name}'",
        "index": index,
        "type": rule["json_type"],
    }
    if rule.get("source_type"):
        prop["source-type"] = rule["source_type"]
    elif ftype != rule["json_type"]:
        prop["source-type"] = ftype
    if field.get("title"):
        prop["title"] = field["title"]
    if field.get("format") and field["format"] != "default":
        prop["fieldFormat"] = field["format"]
    if field.get("rdfType"):
        prop["valueURL"] = field["rdfType"]
    for key, target in CONSTRAINT_KEYS.items():
        value = (field.get("constraints") or {}).get(key)
        if value is None or key == "required":
            continue
        if target == "pattern" and prop["type"] != "string":
            prop["sourcePattern"] = value     # frictionless allows it; JSON Schema does not on numbers
            continue
        prop[target] = value
    for key, value in field.items():
        if key not in FIELD_KEYS_HANDLED:
            prop.setdefault(key, value)
    return prop


# ---- resource -> Dataset ------------------------------------------------------

def resource_description(value, rule, ctx):
    if value:
        return value
    res = ctx.node
    what = "Inline data" if res.get("inline") else f"File '{res.get('path')}'"
    text = f"{what} of resource '{res.get('name')}' in Data Package '{_settings(ctx)['name']}'"
    fields = (res.get("schema") or {}).get("fields")
    if fields:
        text += f" ({len(fields)} columns)"
    return text


def package_author(value, rule, ctx):
    return ", ".join(_contributors(ctx, "author") or _contributors(ctx)) \
        or _settings(ctx).get("author") or None


def package_date(value, rule, ctx):
    return _settings(ctx)["date_published"]


def package_keywords(value, rule, ctx):
    return list(_settings(ctx).get("keywords") or []) or None


def package_license(value, rule, ctx):
    return (_license_of(ctx.node.get("licenses")) or _license_of(_package(ctx).get("licenses"))
            or _settings(ctx).get("license") or None)


def resource_format(value, rule, ctx):
    res = ctx.node
    if res.get("mediatype"):
        return res["mediatype"]
    if res.get("inline"):
        return "application/json"
    if res.get("format"):
        guessed, _ = mimetypes.guess_type("x." + res["format"])
        if guessed:
            return guessed
    return encoding_format_of(res.get("path") or "")


def resource_local_path(value, rule, ctx):
    return ctx.node.get("local_path") or None


def resource_content_url(value, rule, ctx):
    res = ctx.node
    return res["path"] if res.get("remote") else None


def resource_size(value, rule, ctx):
    size = ctx.node.get("size")
    return str(size) if size is not None else None


def resource_hash(value, rule, ctx):
    if not value:
        return None
    text = str(value)
    if ":" in text:                      # sha256:..., sha1:... -> keep the algorithm visible
        ctx.node_extras["hashAlgorithm"], text = text.split(":", 1)
    return text


def resource_schema_ref(value, rule, ctx):
    ark = ctx.extras["guid_map"].get("schema:" + ctx.node["name"])
    return {"@id": ark} if ark else None


def sources_refs(value, rule, ctx):
    sources = value or _package(ctx).get("sources") or []
    out = []
    for s in sources:
        if isinstance(s, dict):
            out.append(s.get("path") or s.get("title"))
        elif s:
            out.append(str(s))
    return [s for s in out if s] or None


# ---- schema -> Schema -------------------------------------------------------------

def schema_name(value, rule, ctx):
    return f"Schema for resource '{ctx.node['name']}'"


def schema_description(value, rule, ctx):
    res = ctx.node
    fields = res["schema"]["fields"]
    text = (f"Table Schema of resource '{res['name']}' ({res.get('title') or res.get('path')}) "
            f"in Data Package '{_settings(ctx)['name']}': {len(fields)} typed columns")
    keys = res["schema"].get("primaryKey")
    if keys:
        keys = keys if isinstance(keys, list) else [keys]
        text += f"; primary key {', '.join(keys)}"
    return text


def json_schema_ref(value, rule, ctx):
    return {"@id": JSON_SCHEMA}


def schema_properties(value, rule, ctx):
    res = ctx.node
    return {f["name"]: field_property(f, i, res["name"])
            for i, f in enumerate(res["schema"]["fields"]) if f.get("name")}


def schema_required(value, rule, ctx):
    return [f["name"] for f in ctx.node["schema"]["fields"]
            if (f.get("constraints") or {}).get("required")] or None


def schema_separator(value, rule, ctx):
    res = ctx.node
    dialect = res.get("dialect") or {}
    if dialect.get("delimiter"):
        return dialect["delimiter"]
    if (res.get("format") or "").lower() == "tsv" or str(res.get("path") or "").lower().endswith(".tsv"):
        return "\t"
    return ","


def schema_header(value, rule, ctx):
    return (ctx.node.get("dialect") or {}).get("header", True)


def _as_list(value):
    return value if isinstance(value, list) else [value]


def schema_primary_key(value, rule, ctx):
    key = ctx.node["schema"].get("primaryKey")
    return _as_list(key) if key else None


def schema_foreign_keys(value, rule, ctx):
    return ctx.node["schema"].get("foreignKeys") or None


def schema_missing_values(value, rule, ctx):
    values = ctx.node["schema"].get("missingValues")
    return values if values else None


def constant_object(value, rule, ctx):
    return "object"


def constant_false(value, rule, ctx):
    return False


# ---- descriptor -> Dataset ----------------------------------------------------

def descriptor_description(value, rule, ctx):
    p = _package(ctx)
    return (f"Frictionless Data Package descriptor for '{_settings(ctx)['name']}'"
            + (f" (package name '{p['name']}')" if p.get("name") else "")
            + f": {len(ctx.source['resources'])} resource(s)")


def constant_json(value, rule, ctx):
    return "application/json"


IMPORT_PARSERS = {
    "scalar": scalar,
    "drop": drop,
    "resource_description": resource_description,
    "package_author": package_author,
    "package_date": package_date,
    "package_keywords": package_keywords,
    "package_license": package_license,
    "resource_format": resource_format,
    "resource_local_path": resource_local_path,
    "resource_content_url": resource_content_url,
    "resource_size": resource_size,
    "resource_hash": resource_hash,
    "resource_schema_ref": resource_schema_ref,
    "sources_refs": sources_refs,
    "schema_name": schema_name,
    "schema_description": schema_description,
    "json_schema_ref": json_schema_ref,
    "schema_properties": schema_properties,
    "schema_required": schema_required,
    "schema_separator": schema_separator,
    "schema_header": schema_header,
    "schema_primary_key": schema_primary_key,
    "schema_foreign_keys": schema_foreign_keys,
    "schema_missing_values": schema_missing_values,
    "constant_object": constant_object,
    "constant_false": constant_false,
    "descriptor_description": descriptor_description,
    "constant_json": constant_json,
}


# ============================================================================
# Export parsers (EVI crate -> Data Package): ``value`` is the Dataset/Schema
# node's property named by the rule's target_property.
# ============================================================================

JSON_TO_FRICTIONLESS = {"string": "string", "integer": "integer", "number": "number",
                        "boolean": "boolean", "array": "array", "object": "object"}
PROPERTY_KEYS_HANDLED = {"description", "index", "type", "source-type", "title", "fieldFormat",
                         "valueURL", "value-url", "value_url", "pattern", "sourcePattern",
                         "minimum", "maximum", "enum", "minLength", "maxLength", "unique",
                         "min-items", "max-items", "unique-items", "properties", "items"}


def x_scalar(value, rule, ctx):
    return scalar(value, rule, ctx)


def x_identity(value, rule, ctx):
    return value if value not in (None, "", [], {}) else None


def x_int(value, rule, ctx):
    try:
        return int(str(value).strip()) if value not in (None, "") else None
    except ValueError:
        return None


def resource_slug(text):
    """A Frictionless resource/package name: lower-case, [a-z0-9._-] only."""
    import re
    slug = re.sub(r"[^a-z0-9._-]+", "-", str(text or "").lower()).strip("-.")
    return slug or "resource"


def x_resource_name(value, rule, ctx):
    return resource_slug(value or ctx.node.get("name") or ctx.node.get("@id"))


def x_description(value, rule, ctx):
    """Drop the sentence resource_description synthesised on import."""
    if not value or str(value).startswith(("File '", "Inline data of resource '")):
        return None
    return str(value)


def x_path(value, rule, ctx):
    return value or ctx.node.get("contentUrl") or None


def x_mediatype(value, rule, ctx):
    return value if value and "/" in str(value) else None


def x_format(value, rule, ctx):
    path = ctx.node.get("localPath") or ctx.node.get("contentUrl") or ""
    ext = os.path.splitext(str(path).split("?")[0])[1].lstrip(".").lower()
    if ext:
        return ext
    if value and "/" in str(value):
        guessed = mimetypes.guess_extension(str(value))
        return guessed.lstrip(".") if guessed else None
    return str(value) if value else None


def x_hash(value, rule, ctx):
    if not value:
        return None
    algorithm = ctx.node.get("hashAlgorithm")
    return f"{algorithm}:{value}" if algorithm else str(value)


def license_entry(license_value):
    text = str(license_value)
    return {"path": text} if text.startswith(("http://", "https://")) else {"name": text}


def x_licenses(value, rule, ctx):
    """A resource licence only when it differs from the package's."""
    if not value or value == ctx.extras.get("package_license"):
        return None
    return [license_entry(value)]


def x_sources(value, rule, ctx):
    if not value:
        return None
    out = []
    for s in value if isinstance(value, list) else [value]:
        text = s.get("@id") if isinstance(s, dict) else str(s)
        if text:
            out.append({"path": text} if text.startswith(("http://", "https://")) else {"title": text})
    return out or None


def property_to_field(name: str, prop: dict, required: bool) -> dict:
    """One EVI Property -> one Table Schema field (the inverse of field_property)."""
    ftype = prop.get("source-type") or JSON_TO_FRICTIONLESS.get(prop.get("type"), "any")
    if ftype not in FIELD_TYPES:
        ftype = "any"
    field = {"name": name, "type": ftype}
    if prop.get("title"):
        field["title"] = prop["title"]
    description = prop.get("description")
    if description and not description.startswith(f"Column '{name}' of resource"):
        field["description"] = description
    if prop.get("fieldFormat"):
        field["format"] = prop["fieldFormat"]
    rdf = prop.get("valueURL") or prop.get("value-url") or prop.get("value_url")
    if rdf:
        field["rdfType"] = rdf
    constraints = {}
    if required:
        constraints["required"] = True
    for key in ("minimum", "maximum", "enum", "minLength", "maxLength", "unique"):
        if prop.get(key) is not None:
            constraints[key] = prop[key]
    pattern = prop.get("pattern") or prop.get("sourcePattern")
    if pattern:
        constraints["pattern"] = pattern
    if constraints:
        field["constraints"] = constraints
    for key, val in prop.items():
        if key not in PROPERTY_KEYS_HANDLED:
            field.setdefault(key, val)
    return field


def x_fields(value, rule, ctx):
    props = value or {}
    required = set(ctx.node.get("required") or [])

    def order(item):
        idx = item[1].get("index")
        return (0, int(idx)) if isinstance(idx, int) or str(idx).isdigit() else (1, 0)

    return [property_to_field(name, prop, name in required)
            for name, prop in sorted(props.items(), key=order)] or None


def x_key(value, rule, ctx):
    if not value:
        return None
    return value[0] if isinstance(value, list) and len(value) == 1 else value


EXPORT_PARSERS = {
    "x_scalar": x_scalar,
    "x_identity": x_identity,
    "x_int": x_int,
    "x_resource_name": x_resource_name,
    "x_description": x_description,
    "x_path": x_path,
    "x_mediatype": x_mediatype,
    "x_format": x_format,
    "x_hash": x_hash,
    "x_licenses": x_licenses,
    "x_sources": x_sources,
    "x_fields": x_fields,
    "x_key": x_key,
}
