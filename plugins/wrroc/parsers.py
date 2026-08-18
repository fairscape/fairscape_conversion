#!/usr/bin/env python3
"""WRROC <-> EVI parsers, in the unified ``fn(value, rule, ctx)`` convention.

Ported verbatim (behaviour-for-behaviour) from the standalone
``workflow_run_crate/wrroc/parsers.py``. The only changes are mechanical:

  - ``ctx`` is now a ``fairscape_conversion.core.Context`` object (state lives in ``ctx.by_id``,
    ``ctx.root``, ``ctx.node`` and the ``ctx.extras`` scratchpad) instead of a
    plain dict;
  - ``rule`` is now a ``PropertyRule`` dataclass, so ``rule["evi_entity"]`` reads
    as ``rule.target_type``;
  - per-node side outputs (``object_split`` parameters) go into
    ``ctx.node_extras`` (the engine merges it into the node).
"""

from __future__ import annotations

import hashlib
import re

from ...core.arks import mint_ark as core_mint_ark, short_hash, slugify

DEFAULT_NAAN = "59853"
IANA_PREFIX = "https://www.iana.org/assignments/media-types/"

_EMPTY = (None, "", [], {})


# ---- shared helpers (ARK minting etc. — fairscape_models has none) ----------

def listify(value):
    if value in _EMPTY:
        return []
    return value if isinstance(value, list) else [value]


def types_of(node):
    return listify(node.get("@type"))


def ref_ids(value):
    ids = []
    for item in listify(value):
        if isinstance(item, dict) and item.get("@id"):
            ids.append(item["@id"])
        elif isinstance(item, str):
            ids.append(item)
    return ids


def mint_ark(prefix, name, original_id, naan=DEFAULT_NAAN):
    return core_mint_ark(naan, f"wrroc-{prefix}", name, original_id)


def iana_tail(value):
    if isinstance(value, str) and value.startswith(IANA_PREFIX):
        return value[len(IANA_PREFIX):]
    return value


def agent_name(agent, by_id):
    if isinstance(agent, dict) and agent.get("@id"):
        node = by_id.get(agent["@id"], {})
        return node.get("name") or agent["@id"]
    return str(agent)


# ============================================================================
# Import parsers (WRROC -> EVI)
# ============================================================================

def _scalar(value, rule, ctx):
    if value in _EMPTY:
        return None
    if isinstance(value, (list, dict)):
        ids = ref_ids(value)
        return ids[0] if ids else str(value)
    return str(value).strip() or None


def _ref_list(value, rule, ctx):
    ids = [ctx.extras["guid_map"].get(i, i) for i in ref_ids(value)]
    return [{"@id": i} for i in ids] if ids else None


def _object_split(value, rule, ctx):
    used, params = [], {}
    for oid in ref_ids(value):
        node = ctx.by_id.get(oid)
        if node is not None and "PropertyValue" in types_of(node):
            inner = [i["@id"] for i in listify(node.get("value"))
                     if isinstance(i, dict) and i.get("@id")]
            if inner:
                used.extend(ctx.extras["guid_map"].get(i, i) for i in inner)
            else:
                params[node.get("name") or oid] = node.get("value")
        else:
            used.append(ctx.extras["guid_map"].get(oid, oid))
    if params:
        ctx.node_extras["parameters"] = params
    return [{"@id": i} for i in used] if used else None


def _formal_params(value, rule, ctx):
    """CreateAction.instrument -> the instrument's input FormalParameters,
    flattened to descriptor strings for ``Computation.parameter``
    (``name: additionalType, default=defaultValue``; type/default only when
    present). The FormalParameter nodes themselves stay dropped."""
    out = []
    for iid in ref_ids(value):
        instrument = ctx.by_id.get(iid, {})
        for fid in ref_ids(instrument.get("input")):
            fp = ctx.by_id.get(fid)
            if fp is None or "FormalParameter" not in types_of(fp):
                continue
            desc = str(fp.get("name") or fid)
            if fp.get("additionalType") not in _EMPTY:
                desc += f": {fp['additionalType']}"
            if fp.get("defaultValue") not in _EMPTY:
                desc += f", default={fp['defaultValue']}"
            out.append(desc)
    return out or None


def _agent_ref(value, rule, ctx):
    ids = ref_ids(value)
    if ids:
        return {"@id": ids[0]}
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ctx.extras["fallback_agent"]


def _desc_min10(value, rule, ctx):
    text = str(value).strip() if value not in _EMPTY else ""
    if rule.target_type == "Computation" and not text:
        node = ctx.node
        parts = [node.get("name", "")]
        for iid in ref_ids(node.get("instrument")):
            instr_desc = ctx.by_id.get(iid, {}).get("description")
            if instr_desc:
                parts.append(instr_desc)
        text = " — ".join(p for p in parts if p)
    if len(text) >= 10:
        return text
    node = ctx.node
    name = node.get("name") or node.get("alternateName") or node.get("@id")
    tail = f"{rule.target_type} {name} converted from a Workflow Run RO-Crate."
    return f"{text} — {tail}" if text else tail


def _synth_name(value, rule, ctx):
    node = ctx.node
    name = node.get("alternateName") or node.get("name")
    if name:
        return str(name)
    return ctx.node["@id"].rstrip("/").split("/")[-1]


def _format_from_extension(name):
    ext = str(name).rsplit(".", 1)[-1].lower() if "." in str(name) else ""
    known = {"json": "application/json", "csv": "text/csv",
             "tsv": "text/tab-separated-values", "txt": "text/plain"}
    return known.get(ext)


def _synth_format(value, rule, ctx):
    node = ctx.node
    return _format_from_extension(node.get("name") or node.get("@id")) or "text/plain"


def _synth_format_lang(value, rule, ctx):
    for lid in ref_ids(value):
        lang = ctx.by_id.get(lid, {})
        label = lang.get("alternateName") or lang.get("name")
        if label:
            version = lang.get("version")
            return f"{label} {version}" if version else str(label)
    return _synth_format(value, rule, ctx)


def _synth_format_file(value, rule, ctx):
    if value not in _EMPTY:
        return iana_tail(value)
    node = ctx.node
    for pid in ref_ids(node.get("exampleOfWork")):
        fmt = ctx.by_id.get(pid, {}).get("encodingFormat")
        if fmt:
            return iana_tail(fmt)
    return _format_from_extension(node.get("alternateName") or "") or "text/plain"


def _synth_datepub(value, rule, ctx):
    return ctx.extras.get("workflow_end_time") or ctx.root.get("datePublished") or "unknown"


def _synth_keywords(value, rule, ctx):
    keywords = listify(ctx.root.get("keywords"))
    return [str(k) for k in keywords] or ["wrroc", "workflow-run"]


def _synth_author(value, rule, ctx):
    return agent_name(ctx.extras["fallback_agent"], ctx.by_id)


def _passthrough(value, rule, ctx):
    return None if value in _EMPTY else value


IMPORT_PARSERS = {
    "scalar": _scalar,
    "ref_list": _ref_list,
    "object_split": _object_split,
    "formal_params": _formal_params,
    "agent_ref": _agent_ref,
    "desc_min10": _desc_min10,
    "synth_name": _synth_name,
    "synth_format": _synth_format,
    "synth_format_lang": _synth_format_lang,
    "synth_format_file": _synth_format_file,
    "synth_datepub": _synth_datepub,
    "synth_keywords": _synth_keywords,
    "synth_author": _synth_author,
    "passthrough": _passthrough,
    "parent_link": lambda value, rule, ctx: None,   # set by the link hook
    "drop": lambda value, rule, ctx: None,
}


# ============================================================================
# Export parsers (EVI -> WRROC Process Run Crate)
# ============================================================================

def _x_scalar(value, rule, ctx):
    return None if value in _EMPTY else value


def _x_ref_list(value, rule, ctx):
    ids = [ctx.extras["restore"].get(i, i) for i in ref_ids(value)]
    return [{"@id": i} for i in ids] if ids else None


def _x_ref_list_first(value, rule, ctx):
    refs = _x_ref_list(value, rule, ctx)
    return refs[0] if refs else None


def _x_agent_export(value, rule, ctx):
    if isinstance(value, dict) and value.get("@id"):
        return {"@id": ctx.extras["restore"].get(value["@id"], value["@id"])}
    if isinstance(value, str) and value.strip() and value.strip() != "Unknown":
        return ctx.extras["mint_person"](value.strip())
    return None


def _x_name_export(value, rule, ctx):
    return None if value in _EMPTY else str(value)


EXPORT_PARSERS = {
    "scalar": _x_scalar,
    "ref_list": _x_ref_list,
    "ref_list_first": _x_ref_list_first,
    "agent_export": _x_agent_export,
    "name_export": _x_name_export,
    "passthrough": _x_scalar,
}
