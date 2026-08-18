#!/usr/bin/env python3
"""Shared round-trip helpers used by the bidirectional plugins.

Two mechanisms recur across the converters:

  1. A **forward marker** stamped on the root (``fromD4D`` / ``fromWRROC``) so
     the reverse trip knows the crate came from this converter and can restore
     original ids / decode tagged strings for full fidelity.
  2. **Tagged pipe strings** — d4d collapses a sub-entity into one labelled
     string ``Field: <field> | key: val | key2: val2`` on the way out and splits
     it back on the way in. Kept here so both directions share one definition
     and can never disagree on the delimiters.
"""

from __future__ import annotations

SEP = " | "          # between fields inside one item (comma-safe)
ITEM_SEP = " ; "     # between items merged into a single scalar string
FIELD_TAG = "Field: "

_EMPTY = (None, "", [], {})


# ---- forward markers --------------------------------------------------------

def stamp(root: dict, marker: str) -> None:
    root[marker] = True


def came_from(root: dict, marker: str) -> bool:
    return bool(root.get(marker))


def restore_map(graph: list[dict]) -> dict:
    """node ``@id`` -> original ``identifier`` (when the import trip kept one)."""
    out = {}
    for node in graph:
        ident = node.get("identifier")
        if isinstance(ident, str) and ident and node.get("@id"):
            out[node["@id"]] = ident
    return out


# ---- tagged pipe strings (d4d flatten / reverse_flatten) --------------------

def flatten_value(value) -> str:
    """A scalar / list / dict collapsed into one short comma-joined string."""
    if value in _EMPTY:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return ", ".join(flatten_value(v) for v in value if v not in _EMPTY)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {flatten_value(v)}" for k, v in value.items() if v not in _EMPTY)
    return str(value)


def tag_item(field: str, item) -> str:
    """One labelled pipe string for a sub-entity (``id`` dropped, ``Field:`` prefix)."""
    if not isinstance(item, dict):
        return f"{FIELD_TAG}{field}{SEP}{flatten_value(item)}"
    parts = [f"{FIELD_TAG}{field}"]
    for key, val in item.items():
        if key == "id" or val in _EMPTY:
            continue
        parts.append(f"{key}: {flatten_value(val)}")
    return SEP.join(parts)


def tag_items(field: str, value) -> list[str]:
    """A field value (single object or list) -> list of labelled strings."""
    if value in _EMPTY:
        return []
    items = value if isinstance(value, list) else [value]
    return [tag_item(field, it) for it in items if it not in _EMPTY]


def untag_item(s: str):
    """``'Field: f | k: v'`` -> ``(f, {k: v})``; untagged -> ``(None, {description: s})``."""
    s = (s or "").strip()
    if not s:
        return None, {}
    if not s.startswith(FIELD_TAG):
        return None, {"description": s}
    parts = s.split(SEP)
    field = parts[0][len(FIELD_TAG):].strip()
    obj = {}
    for seg in parts[1:]:
        key, sep, val = seg.partition(": ")
        val = val.strip()
        if not sep:
            if key.strip():
                obj.setdefault("description", key.strip())
        elif val:
            obj[key.strip()] = val
    return field, obj
