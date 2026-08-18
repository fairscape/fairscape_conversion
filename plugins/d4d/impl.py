#!/usr/bin/env python3
"""D4D <-> RO-Crate conversion: ``D4dPlugin`` on the unified entities/properties CSVs.

Forward (D4D -> RO-Crate) rides the shared pipeline: ``pre`` turns the
D4D document into records (one root record + one per digital object), a
``map_record`` override does d4d's genuinely bespoke many-to-one merge (several
D4D fields collapse onto one crate field) by composing the registered import
parsers, and ``assemble`` builds the crate shell. Reverse (RO-Crate -> D4D) is
a bespoke ``export`` override — like wrroc's — dispatching through the
registered export parsers. Ported from ``convertV2/d4d_to_rocrate.py`` +
``rocrate_to_d4d.py``.

One deliberate difference from the old code: the pipeline drops a node whose
``@id`` was already emitted (first writer wins), where the original could emit
duplicate blank-node ids (``_:{field}``) when several items in one field had no
id — duplicate ``@id``s in a crate graph are invalid, so the dedup is a fix,
not a regression.
"""

from __future__ import annotations

import copy
import warnings

from ...core import Context, PluginBase, Record, run_import_parser
from ...core.roundtrip import ITEM_SEP
from ...core.schema import EntityRule
from .parsers import EXPORT_PARSERS, IMPORT_PARSERS, reverse_kind

_EMPTY = (None, "", [], {})

ROOT_TYPE = ["Dataset", "https://w3id.org/EVI#ROCrate"]
CONTEXT = {
    "@vocab": "https://schema.org/",
    "evi": "https://w3id.org/EVI#",
    "rai": "http://mlcommons.org/croissant/RAI/",
    "prov": "http://www.w3.org/ns/prov#",
    "d4d": "https://w3id.org/bridge2ai/data-sheets-schema/",
}

_SKIP_KEYS = {"@id", "@type", "@context", "metadataType", "guid", "hasPart", "fromD4D"}

# Synthetic entity rule for the single root record (the whole D4D document).
ROOT_RULE = EntityRule(source_type="__root__", target_type="ROCrate", id_strategy="keep")


# ============================================================================
# Runtime grouping straight from the unified Mapping (shared by both trips)
# ============================================================================

def _groups_by_target(mapping):
    """Property rules grouped per target property.

    ``cardinality`` on a property row is the SOURCE field's multivalued flag
    (d4d's original ``multivalued`` column); the target cardinality is derived
    exactly as the old build step did (list if any multivalued source is not
    ``flatten_str``). Sources are sorted ``reverse_primary``-first so the
    reverse trip knows which D4D field owns a merged value.
    """
    groups: dict = {}
    for r in mapping.properties:
        entry = groups.setdefault(r.target_property, {"cardinality": "scalar", "sources": []})
        source_multivalued = r.cardinality == "list"
        if source_multivalued and r.import_parser != "flatten_str":
            entry["cardinality"] = "list"
        entry["sources"].append({
            "d4d_field": r.source_property,
            "parser": r.import_parser,
            "reverse_primary": r.reverse_primary,
            "multivalued": source_multivalued,
            "rule": r,
        })
    for entry in groups.values():
        entry["sources"].sort(key=lambda s: not s["reverse_primary"])
    return groups


def _dobj_rules(mapping):
    return [e for e in mapping.entities if e.target_type == "DigitalObject"]


def _dobj_spec(rule):
    return {
        "d4d_field": rule.source_type,
        "additionalType": rule.target_type_iri[0] if rule.target_type_iri else None,
        "url_field": rule.id_column,
    }


# ============================================================================
# Forward: D4D -> RO-Crate (pipeline hooks)
# ============================================================================

def _strip_empty(node: dict, keep: tuple = ()) -> dict:
    return {k: v for k, v in node.items() if k in keep or v not in (None, [], {})}


def _build_digital_object(item, root_author, spec):
    from fairscape_models.digital_object import DigitalObject

    guid = item.get("id") or item.get("@id") or f"_:{spec['d4d_field']}"
    name = item.get("name") or str(guid)
    description = item.get("description") or name
    url = item.get(spec["url_field"])
    if isinstance(url, list):
        urls = [str(u) for u in url if u]
        url = urls[0] if len(urls) == 1 else (urls or None)

    do = DigitalObject.model_construct(guid=str(guid), name=name,
                                       description=description, author=root_author)
    do.additionalType = spec["additionalType"]
    if url:
        do.url = url
    return do


def _assemble_root_args(ctx: Context, d4d: dict) -> dict:
    """Merge every D4D source field onto its crate target (many-to-one).

    Reduce heuristic (verbatim from the old compiled runtime): list targets
    keep everything; a scalar target takes the single result, or the
    ``ITEM_SEP`` join when every source is a flatten parser, or the primary
    result otherwise.
    """
    args = {}
    for attr, spec in ctx.extras["groups"].items():
        results = []
        for src in spec["sources"]:
            value = d4d.get(src["d4d_field"])
            if value in _EMPTY:
                continue
            out = run_import_parser(ctx, src["rule"], value)
            if out in _EMPTY:
                continue
            results.extend(out) if isinstance(out, list) else results.append(out)
        if not results:
            continue
        if spec["cardinality"] != "scalar":
            args[attr] = results
        elif len(results) == 1:
            args[attr] = results[0]
        elif all(s["parser"] in ("flatten", "flatten_str") for s in spec["sources"]):
            args[attr] = ITEM_SEP.join(map(str, results))
        else:
            args[attr] = results[0]
    return args


class D4dPlugin(PluginBase):
    """Datasheets for Datasets (D4D) <-> RO-Crate, bidirectional."""

    name = "d4d"
    import_parsers = IMPORT_PARSERS
    export_parsers = EXPORT_PARSERS

    def pre(self, ctx: Context):
        """One root record (the whole D4D document) + one per digital object."""
        d4d = ctx.source
        ctx.extras["groups"] = _groups_by_target(ctx.mapping)
        records = [Record(data=d4d, rule=ROOT_RULE)]
        for rule in _dobj_rules(ctx.mapping):
            items = d4d.get(rule.source_type) or []
            if isinstance(items, dict):
                items = list(items.values()) if all(isinstance(v, dict) for v in items.values()) else [items]
            records.extend(Record(data=item, rule=rule) for item in items)
        ctx.records = records

    def select_rules(self, ctx: Context, rec: Record):
        # Rules key on the source field group, resolved inside map_record.
        return []

    def map_record(self, ctx: Context, rec: Record, rules) -> dict:
        if rec.rule is ROOT_RULE:
            return _map_root(ctx, rec.data)
        do = _build_digital_object(rec.data, ctx.extras["root_author"], _dobj_spec(rec.rule))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return _strip_empty(do.model_dump(by_alias=True, exclude_none=True))

    def assemble(self, ctx: Context) -> dict:
        root_id = ctx.order[0]
        ctx.out_nodes[root_id]["hasPart"] = [{"@id": g} for g in ctx.order[1:]]
        crate = {
            "@context": CONTEXT,
            "@graph": [
                {"@id": "ro-crate-metadata.json", "@type": "CreativeWork",
                 "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
                 "about": {"@id": root_id}},
                *[ctx.out_nodes[g] for g in ctx.order],
            ],
        }
        if ctx.extras.get("validate", True):
            from fairscape_models.rocrate import ROCrateV1_2
            ROCrateV1_2.model_validate(copy.deepcopy(crate))
        return crate

    def export(self, source, options: dict) -> dict:
        """RO-Crate -> D4D: bespoke reverse driver (see convert_reverse below)."""
        return convert_reverse(source, self)


def _map_root(ctx: Context, d4d: dict) -> dict:
    from fairscape_models.rocrate import ROCrateMetadataElem

    root_args = _assemble_root_args(ctx, d4d)
    root_id = d4d.get("id") or d4d.get("doi") or "./"
    root_args.setdefault("name", d4d.get("title") or d4d.get("name") or str(root_id))
    root_args.setdefault("description", d4d.get("description") or root_args["name"])
    root_args.setdefault("keywords", [])
    root_args.setdefault("version", "0.1.0")
    root_args.setdefault("author", root_args.get("publisher") or "Unknown")
    root_args["guid"] = str(root_id)
    root_args["metadataType"] = ROOT_TYPE
    ctx.extras["root_author"] = root_args["author"]

    root = ROCrateMetadataElem.model_construct(**root_args)
    root.fromD4D = True
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _strip_empty(root.model_dump(by_alias=True, exclude_none=True),
                            keep=("keywords", "hasPart"))


# ============================================================================
# Reverse: RO-Crate -> D4D (bespoke driver composing the export registry)
# ============================================================================

def _find_root_entity(crate):
    graph = crate.get("@graph", [])
    descriptor = next((e for e in graph if e.get("@id") == "ro-crate-metadata.json"), None)
    if not descriptor:
        return None
    about = descriptor.get("about")
    root_id = about.get("@id") if isinstance(about, dict) else about
    if not root_id:
        return None
    return next((e for e in graph if e.get("@id") == root_id), None)


def _build_alias_to_attr(groups):
    from fairscape_models.rocrate import ROCrateMetadataElem

    alias_to_attr = {}
    for name, field in ROCrateMetadataElem.model_fields.items():
        alias_to_attr.setdefault(field.alias or name, name)
        alias_to_attr.setdefault(name, name)
    for attr in groups:
        alias_to_attr.setdefault(attr, attr)
    return alias_to_attr


def _merge(d4d, partial):
    for field, value in partial.items():
        if field in d4d and isinstance(d4d[field], list) and isinstance(value, list):
            d4d[field].extend(value)
        else:
            d4d.setdefault(field, value)


def _route(d4d, field, obj, multivalued):
    if multivalued.get(field, True):
        d4d.setdefault(field, []).append(obj)
    else:
        d4d.setdefault(field, obj)


def _reverse_digital_object(node, dobj_specs):
    add_type = node.get("additionalType")
    spec = next((s for s in dobj_specs if s["additionalType"] == add_type), None)
    if spec is None:
        return None, None
    item = {}
    desc = node.get("description")
    name = node.get("name")
    if name and name != node.get("@id") and name != desc:
        item["name"] = name
    if desc:
        item["description"] = desc
    url = node.get("url")
    if url not in _EMPTY:
        url_field = spec["url_field"]
        if url_field == "external_resources":
            item[url_field] = url if isinstance(url, list) else [url]
        else:
            item[url_field] = url
    return spec["d4d_field"], item


def convert_reverse(crate: dict, plugin) -> dict:
    groups = _groups_by_target(plugin.mapping)
    multivalued = {src["d4d_field"]: src["multivalued"]
                   for entry in groups.values() for src in entry["sources"]}

    root = _find_root_entity(crate)
    if root is None:
        raise ValueError("Could not find root dataset entity in RO-Crate")

    ctx = Context(plugin, "export", crate)
    ctx.extras["from_d4d"] = bool(root.get("fromD4D"))
    ctx.extras["multivalued"] = multivalued
    alias_to_attr = _build_alias_to_attr(groups)

    d4d = {}
    if root.get("@id"):
        d4d["id"] = root["@id"]
    if root.get("name"):
        d4d["name"] = root["name"]

    for key, value in root.items():
        if key in _SKIP_KEYS or value in _EMPTY:
            continue
        attr = key if key in groups else alias_to_attr.get(key)
        entry = groups.get(attr) if attr else None
        if entry is None:
            continue
        parser = plugin.export_parsers[reverse_kind(entry)]
        _merge(d4d, parser(value, entry, ctx))

    dobj_specs = [_dobj_spec(r) for r in _dobj_rules(plugin.mapping)]
    for node in crate.get("@graph", []):
        if not node.get("additionalType"):
            continue
        field, item = _reverse_digital_object(node, dobj_specs)
        if field and item:
            _route(d4d, field, item, multivalued)

    return d4d
