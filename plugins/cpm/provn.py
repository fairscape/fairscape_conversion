#!/usr/bin/env python3
"""Minimal PROV-N and PROV-JSON reader/writers for CPM bundles.

The ``prov`` pip package writes PROV-N but cannot read it, and CPM's published
reference bundles are PROV-N files — so this module carries a small, tolerant
PROV-N parser of its own (it accepts the reference crate's quirks: identifiers
containing spaces, ``%%`` datatype suffixes, repeated attribute keys). PROV-XML
and PROV-O(turtle) bundles are out of scope; the profile's other allowed
serialization, PROV-JSON (https://www.w3.org/submissions/prov-json/), is
supported both ways.

Everything is statement-shaped: a :class:`Document` holds prefix declarations
and :class:`Bundle`\\ s, a bundle holds :class:`Statement`\\ s — the statement
name (``entity``, ``used``, …), its positional identifier arguments (``None``
for the ``-`` placeholder), and its ``[key=value]`` attribute pairs. The CPM
interpretation of those statements lives in ``hooks.py``, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Statement:
    name: str
    args: list                                  # positional args: str qualified names, or None for '-'
    attrs: list = field(default_factory=list)   # [(key, value, datatype|None)]
    ident: str = ""                             # optional statement identifier (the 'id;' marker)

    def attr_values(self, key: str) -> list:
        return [v for k, v, _ in self.attrs if k == key]


@dataclass
class Bundle:
    ident: str
    prefixes: dict = field(default_factory=dict)
    statements: list = field(default_factory=list)


@dataclass
class Document:
    prefixes: dict = field(default_factory=dict)
    default_ns: str = ""
    bundles: list = field(default_factory=list)


# ============================================================================
# PROV-N reading
# ============================================================================

_PREFIX_RE = re.compile(r"^prefix\s+(\S+)\s+<([^>]*)>$")
_DEFAULT_RE = re.compile(r"^default\s+<([^>]*)>$")
_STMT_RE = re.compile(r"^([A-Za-z]+)\s*\((.*)\)$", re.S)


def _split_top(text: str) -> list[str]:
    """Split on commas at bracket depth 0, outside quoted strings (double- or
    single-quoted — the spec says double, real files also use single)."""
    parts, depth, quote, start = [], 0, "", 0
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in ('"', "'"):
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return [p.strip() for p in parts]


def _parse_value(raw: str):
    """An attribute value -> (value, datatype|None). Keeps strings as strings."""
    raw = raw.strip()
    datatype = None
    m = re.match(r'''^(".*"|'.*')\s*%%\s*(\S+)$''', raw, re.S)
    if m:
        raw, datatype = m.group(1).strip(), m.group(2)
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1].replace('\\"', '"'), datatype
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        return raw[1:-1].replace("\\'", "'"), datatype
    if re.fullmatch(r"-?\d+", raw):
        return int(raw), "xsd:int"
    if re.fullmatch(r"-?\d*\.\d+", raw):
        return float(raw), "xsd:float"
    return raw, datatype


def _parse_attrs(block: str) -> list:
    attrs = []
    for pair in _split_top(block):
        if not pair or "=" not in pair:
            continue
        key, raw = pair.split("=", 1)
        value, datatype = _parse_value(raw)
        attrs.append((key.strip(), value, datatype))
    return attrs


def _parse_statement(text: str) -> Statement | None:
    m = _STMT_RE.match(text.strip())
    if not m:
        return None
    name, body = m.group(1), m.group(2).strip()
    ident = ""
    if ";" in body:
        head, rest = body.split(";", 1)
        if '"' not in head and "[" not in head:
            ident, body = head.strip(), rest.strip()
    args, attrs = [], []
    for part in _split_top(body):
        if part.startswith("["):
            attrs = _parse_attrs(part[1:-1] if part.endswith("]") else part[1:])
        elif part == "-":
            args.append(None)
        elif part == "":
            continue
        else:
            args.append(part)
    return Statement(name, args, attrs, ident)


def parse_provn(text: str) -> Document:
    doc = Document()
    bundle = None
    buffer = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if buffer:
            buffer += " " + line
            if buffer.count("(") <= buffer.count(")"):
                stmt = _parse_statement(buffer)
                buffer = ""
                if stmt and bundle is not None:
                    bundle.statements.append(stmt)
            continue
        if line in ("document", "endDocument", "endBundle"):
            if line == "endBundle":
                bundle = None
            continue
        m = _PREFIX_RE.match(line)
        if m:
            (bundle.prefixes if bundle else doc.prefixes)[m.group(1)] = m.group(2)
            continue
        m = _DEFAULT_RE.match(line)
        if m:
            doc.default_ns = m.group(1)
            continue
        if line.startswith("bundle "):
            bundle = Bundle(line.split(None, 1)[1].strip())
            doc.bundles.append(bundle)
            continue
        if line.count("(") > line.count(")"):
            buffer = line
            continue
        stmt = _parse_statement(line)
        if stmt and bundle is not None:
            bundle.statements.append(stmt)
    return doc


# ============================================================================
# PROV-JSON reading (https://www.w3.org/submissions/prov-json/)
# ============================================================================

# PROV-JSON statement key -> ordered positional argument keys.
_PROVJSON_ARGS = {
    "entity": (),
    "activity": ("prov:startTime", "prov:endTime"),
    "agent": (),
    "used": ("prov:activity", "prov:entity", "prov:time"),
    "wasGeneratedBy": ("prov:entity", "prov:activity", "prov:time"),
    "wasDerivedFrom": ("prov:generatedEntity", "prov:usedEntity",
                       "prov:activity", "prov:generation", "prov:usage"),
    "wasAttributedTo": ("prov:entity", "prov:agent"),
    "wasAssociatedWith": ("prov:activity", "prov:agent", "prov:plan"),
    "specializationOf": ("prov:specificEntity", "prov:generalEntity"),
    "alternateOf": ("prov:alternate1", "prov:alternate2"),
    "wasInvalidatedBy": ("prov:entity", "prov:activity", "prov:time"),
    "wasInformedBy": ("prov:informed", "prov:informant"),
    "actedOnBehalfOf": ("prov:delegate", "prov:responsible", "prov:activity"),
    "hadMember": ("prov:collection", "prov:entity"),
}
_ELEMENT_KEYS = ("entity", "activity", "agent")


def _provjson_value(v):
    if isinstance(v, dict) and "$" in v:
        return v["$"], v.get("type")
    return v, None


def _provjson_statements(section: dict) -> list[Statement]:
    out = []
    for name, arg_keys in _PROVJSON_ARGS.items():
        for ident, body in (section.get(name) or {}).items():
            body = body or {}
            if name in _ELEMENT_KEYS:
                args = [ident] + [body.get(k) for k in arg_keys]
                while len(args) > 1 and args[-1] is None:
                    args.pop()
                consumed = set(arg_keys)
            else:
                args = [body.get(k) for k in arg_keys]
                while args and args[-1] is None:
                    args.pop()
                consumed = set(arg_keys)
            attrs = []
            for k, v in body.items():
                if k in consumed:
                    continue
                for single in (v if isinstance(v, list) else [v]):
                    value, datatype = _provjson_value(single)
                    attrs.append((k, value, datatype))
            out.append(Statement(name, args, attrs,
                                 "" if name in _ELEMENT_KEYS else ident))
    return out


def parse_provjson(doc_json: dict) -> Document:
    doc = Document(prefixes=dict(doc_json.get("prefix") or {}))
    doc.default_ns = doc.prefixes.pop("default", "")
    for bundle_id, section in (doc_json.get("bundle") or {}).items():
        bundle = Bundle(bundle_id, prefixes=dict(section.get("prefix") or {}))
        bundle.statements = _provjson_statements(section)
        doc.bundles.append(bundle)
    if not doc.bundles and any(doc_json.get(k) for k in _PROVJSON_ARGS):
        bundle = Bundle("bundle")
        bundle.statements = _provjson_statements(doc_json)
        doc.bundles.append(bundle)
    return doc


# ============================================================================
# Writers
# ============================================================================

def _fmt_value(value, datatype) -> str:
    if datatype in ("xsd:int",) and isinstance(value, int):
        return str(value)
    text = str(value).replace('"', '\\"')
    quoted = f'"{text}"'
    if datatype and datatype != "xsd:int":
        return f"{quoted} %% {datatype}"
    return quoted


def _fmt_statement(stmt: Statement) -> str:
    parts = ["-" if a is None else str(a) for a in stmt.args]
    if stmt.name == "activity" and stmt.attrs and len(parts) == 1:
        parts += ["-", "-"]          # keep the conventional (id, start, end, [..]) shape
    if stmt.attrs:
        inner = ", ".join(f"{k}={_fmt_value(v, d)}" for k, v, d in stmt.attrs)
        parts.append(f"[{inner}]")
    return f"{stmt.name}({', '.join(parts)})"


def provn_dumps(doc: Document) -> str:
    lines = ["document"]
    if doc.default_ns:
        lines.append(f"  default <{doc.default_ns}>")
    for name, uri in doc.prefixes.items():
        lines.append(f"  prefix {name} <{uri}>")
    for bundle in doc.bundles:
        lines.append("")
        lines.append(f"  bundle {bundle.ident}")
        for name, uri in bundle.prefixes.items():
            lines.append(f"    prefix {name} <{uri}>")
        if bundle.prefixes:
            lines.append("")
        for stmt in bundle.statements:
            lines.append(f"    {_fmt_statement(stmt)}")
        lines.append("  endBundle")
    lines.append("endDocument")
    return "\n".join(lines) + "\n"


def provjson_dumps(doc: Document) -> dict:
    def value_json(value, datatype):
        if datatype:
            return {"$": value, "type": datatype}
        return value

    out: dict = {}
    if doc.prefixes or doc.default_ns:
        out["prefix"] = dict(doc.prefixes)
        if doc.default_ns:
            out["prefix"]["default"] = doc.default_ns
    bundles: dict = {}
    for bundle in doc.bundles:
        section: dict = {}
        if bundle.prefixes:
            section["prefix"] = dict(bundle.prefixes)
        counters: dict[str, int] = {}
        for stmt in bundle.statements:
            table = section.setdefault(stmt.name, {})
            body: dict = {}
            if stmt.name in _ELEMENT_KEYS:
                key = stmt.args[0]
                body = table.get(key, {})
                for arg_key, arg in zip(_PROVJSON_ARGS[stmt.name], stmt.args[1:]):
                    if arg is not None:
                        body[arg_key] = arg
            else:
                counters[stmt.name] = counters.get(stmt.name, 0) + 1
                key = stmt.ident or f"_:{stmt.name[:2].lower()}{counters[stmt.name]}"
                for arg_key, arg in zip(_PROVJSON_ARGS[stmt.name], stmt.args):
                    if arg is not None:
                        body[arg_key] = arg
            for k, v, d in stmt.attrs:
                encoded = value_json(v, d)
                if k in body:
                    prev = body[k] if isinstance(body[k], list) else [body[k]]
                    body[k] = prev + [encoded]
                else:
                    body[k] = encoded
            table[key] = body
        bundles[bundle.ident] = section
    out["bundle"] = bundles
    return out
