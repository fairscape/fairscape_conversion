#!/usr/bin/env python3
"""D4D <-> RO-Crate parsers.

Forward parsers follow the unified ``fn(value, rule, ctx)`` signature. The
tagged-pipe-string flatten/unflatten machinery is the shared
``fairscape_conversion.core.roundtrip`` helpers, so both directions agree on the delimiters.

Reverse is genuinely per-target-group (many D4D fields collapse onto one crate
field, so the reverse trip rebuilds them by the group's ``reverse_primary``
source). Its parsers take the group ``entry`` as ``rule`` and read ``from_d4d`` /
``multivalued`` from ``ctx.extras`` — still one signature, just a group-shaped
``rule``. Ported from ``convertV2/d4d_to_rocrate.py`` + ``rocrate_to_d4d.py``.
"""

from __future__ import annotations

from ...core.roundtrip import ITEM_SEP, flatten_value, tag_items, untag_item

_EMPTY = (None, "", [], {})


# ============================================================================
# Forward parsers (D4D -> RO-Crate)
# ============================================================================

def parse_scalar(value):
    if value in _EMPTY:
        return None
    if isinstance(value, (list, dict)):
        return flatten_value(value) or None
    return str(value).strip() or None


def parse_string_list(value):
    if value in _EMPTY:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value if v not in _EMPTY]
    return [str(value)]


def flatten(field, value):
    """A D4D field value -> list of labelled pipe strings."""
    return tag_items(field, value)


def flatten_str(field, value):
    """Like flatten, collapsed to a single ITEM_SEP-joined string."""
    items = tag_items(field, value)
    return ITEM_SEP.join(items) if items else None


IMPORT_PARSERS = {
    "scalar": lambda value, rule, ctx: parse_scalar(value),
    "string_list": lambda value, rule, ctx: parse_string_list(value),
    "flatten": lambda value, rule, ctx: flatten(rule.source_property, value),
    "flatten_str": lambda value, rule, ctx: flatten_str(rule.source_property, value),
}


# ============================================================================
# Reverse parsers (RO-Crate -> D4D) — operate on a target group ``entry``
# ============================================================================

def _route(out, field, obj, multivalued):
    if multivalued.get(field, True):
        out.setdefault(field, []).append(obj)
    else:
        out.setdefault(field, obj)


def reverse_scalar(entry, value, from_d4d, multivalued):
    primary = entry["sources"][0]["d4d_field"]
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value if v not in _EMPTY)
    text = str(value).strip()
    return {primary: text} if text else {}


def reverse_string_list(entry, value, from_d4d, multivalued):
    primary = entry["sources"][0]["d4d_field"]
    if isinstance(value, str):
        value = [value]
    items = [str(v) for v in value if v not in _EMPTY]
    return {primary: items} if items else {}


def reverse_flatten(entry, value, from_d4d, multivalued):
    primary = entry["sources"][0]["d4d_field"]
    items = value if isinstance(value, list) else str(value).split(ITEM_SEP)
    out = {}
    for raw in items:
        raw = raw if isinstance(raw, str) else str(raw)
        field, obj = untag_item(raw)
        target = field if (from_d4d and field) else primary
        if not obj:
            text = raw.strip()
            if not text:
                continue
            obj = {"description": text}
        _route(out, target, obj, multivalued)
    return out


# Uniform-signature adapters — THE export registry: the reverse driver in
# impl.py dispatches through these, and the loader validates CSV names here.
EXPORT_PARSERS = {
    "reverse_scalar": lambda value, rule, ctx: reverse_scalar(
        rule, value, ctx.extras["from_d4d"], ctx.extras["multivalued"]),
    "reverse_string_list": lambda value, rule, ctx: reverse_string_list(
        rule, value, ctx.extras["from_d4d"], ctx.extras["multivalued"]),
    "reverse_flatten": lambda value, rule, ctx: reverse_flatten(
        rule, value, ctx.extras["from_d4d"], ctx.extras["multivalued"]),
}


def reverse_kind(entry):
    """Pick the reverse parser name from the group's primary source + cardinality."""
    primary = entry["sources"][0]
    if primary["parser"] == "string_list":
        return "reverse_string_list"
    if entry["cardinality"] == "list":
        return "reverse_flatten"
    if primary["parser"] in ("flatten", "flatten_str"):
        return "reverse_flatten"
    return "reverse_scalar"
