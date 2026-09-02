#!/usr/bin/env python3
"""CPM <-> EVI: the named parsers the CSVs reference.

Import parsers read the flattened element records ``hooks.pre`` builds (one
dict per PROV element: ``qid`` / ``local`` / ``label`` / ``cpm_type`` /
``attrs`` + every bundle attribute flattened to the top level). EVI-required
fields the bundles cannot supply (author, datePublished, keywords, format) are
synthesized from the crate root the same way the wrroc plugin does.
"""

from __future__ import annotations

import re

from ...core.arks import DEFAULT_NAAN, mint_ark, slugify   # noqa: F401 (re-exported)
from ...core.parsers import identity, scalar

_EMPTY = (None, "", [], {})

# Attribute keys consumed by dedicated rules; everything else lands in
# ``additionalProperty`` so nothing a bundle says is dropped.
CONSUMED_ATTRS = ("sha256", "hash", "filepath", "file", "checkpoint_file",
                  "prov:label", "prov:type")

_KIND_NOUN = {
    "mainActivity": "the main activity",
    "activity": "an activity",
    "transferActivity": "a data transfer (CPM receipt activity)",
    "entity": "an entity",
    "agent": "an agent",
}


def _root_meta(ctx) -> dict:
    return ctx.extras.get("root_meta", {})


def pretty_label(value, rule, ctx):
    """The element's prov:label, else its local name spaced out."""
    label = ctx.node.get("label") or ctx.node.get("local") or ctx.node.get("qid")
    return str(label).strip() or None


def synth_desc(value, rule, ctx):
    """A >=10-char description naming the element's role and source bundle."""
    node = ctx.node
    source_type = node.get("source_type", "")
    noun = _KIND_NOUN.get(source_type, "an element")
    cpm_type = node.get("cpm_type")
    # mainActivity / transferActivity nouns already name the CPM role.
    role = (f" (cpm:{cpm_type})"
            if cpm_type and source_type in ("entity", "agent", "activity") else "")
    bundle = node.get("bundle_id") or "a CPM bundle"
    return (f"{pretty_label(None, rule, ctx)}: {noun}{role} imported from "
            f"CPM provenance bundle {bundle}.")


def synth_author(value, rule, ctx):
    return _root_meta(ctx).get("author") or "Unknown"


def synth_date(value, rule, ctx):
    return _root_meta(ctx).get("datePublished") or "Unknown"


def synth_keywords(value, rule, ctx):
    return _root_meta(ctx).get("keywords") or ["cpm", "provenance"]


def synth_runby(value, rule, ctx):
    """The bundle's sender agent (the org that ran and publishes this part),
    else the crate author, else Unknown."""
    agent = ctx.extras.get("sender_agent_by_bundle", {}).get(ctx.node.get("bundle_id"))
    return agent or _root_meta(ctx).get("author") or "Unknown"


def synth_format(value, rule, ctx):
    """MIME-ish format from a file-path attribute's extension."""
    path = (ctx.node.get("filepath") or ctx.node.get("file")
            or ctx.node.get("checkpoint_file") or "")
    ext = str(path).rsplit(".", 1)[-1].lower() if "." in str(path) else ""
    known = {"json": "application/json", "csv": "text/csv", "txt": "text/plain",
             "h5": "application/x-hdf5", "hdf5": "application/x-hdf5",
             "tif": "image/tiff", "tiff": "image/tiff", "xml": "application/xml"}
    if ext in known:
        return known[ext]
    return "application/octet-stream"


def synth_content_url(value, rule, ctx):
    path = (ctx.node.get("filepath") or ctx.node.get("file")
            or ctx.node.get("checkpoint_file"))
    if path in _EMPTY:
        return None
    path = str(path)
    return path if re.match(r"^[a-z][a-z0-9+.-]*://", path) else f"file://{path}"


def cpm_type_str(value, rule, ctx):
    """cpm_type 'mainActivity' -> 'cpm:mainActivity' (string, as the reference
    bundles themselves write it — CPM has no published namespace URI)."""
    return f"cpm:{value}" if value not in _EMPTY else None


def scalar_or_list(value, rule, ctx):
    if value in _EMPTY:
        return None
    return [str(v) for v in value] if isinstance(value, list) else str(value)


def attrs_parameter(value, rule, ctx):
    """Domain attributes of an activity -> Computation.parameter 'key=value' strings."""
    attrs = value or {}
    out = [f"{k}={v}" for k, v in attrs.items() if k not in CONSUMED_ATTRS]
    return out or None


def attrs_property_values(value, rule, ctx):
    """Domain attributes of an entity -> schema.org additionalProperty."""
    attrs = value or {}
    out = [{"@type": "PropertyValue", "name": k, "value": v}
           for k, v in attrs.items() if k not in CONSUMED_ATTRS]
    return out or None


# ---- cpmfile records (the CPMProvenanceFile crate node itself) --------------

def file_desc(value, rule, ctx):
    if value not in _EMPTY and len(str(value).strip()) >= 10:
        return str(value).strip()
    return "CPM provenance bundle file registered in the source crate."


def file_format(value, rule, ctx):
    """First plain string of the crate node's encodingFormat."""
    values = value if isinstance(value, list) else [value]
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "text/provenance-notation"


def file_kind(value, rule, ctx):
    return ("CPMMetaProvenanceFile" if ctx.node.get("is_meta")
            else "CPMProvenanceFile")


def file_date(value, rule, ctx):
    return (ctx.node.get("dateModified") or _root_meta(ctx).get("datePublished")
            or "Unknown")


IMPORT_PARSERS = {
    "scalar": scalar,
    "identity": identity,
    "pretty_label": pretty_label,
    "synth_desc": synth_desc,
    "synth_author": synth_author,
    "synth_date": synth_date,
    "synth_keywords": synth_keywords,
    "synth_runby": synth_runby,
    "synth_format": synth_format,
    "synth_content_url": synth_content_url,
    "cpm_type_str": cpm_type_str,
    "scalar_or_list": scalar_or_list,
    "attrs_parameter": attrs_parameter,
    "attrs_property_values": attrs_property_values,
    "file_desc": file_desc,
    "file_format": file_format,
    "file_kind": file_kind,
    "file_date": file_date,
}
