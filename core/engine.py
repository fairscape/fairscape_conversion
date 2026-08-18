#!/usr/bin/env python3
"""The shared conversion kernel.

Everything workflow-agnostic lives here: applying property rules with named
parsers, interpolating id/constant templates, and a light ``run_pipeline``
driver that owns the ``map`` stage (per-record via the overridable
``map_record`` hook) and calls the plugin's ``pre`` / ``link`` / ``assemble``
hooks around it.

The kernel is deliberately small. A plugin that does not fit the pipeline (d4d's
many-to-one root merge) still uses the same ``run_parser`` + rule objects — it
just composes them itself. That is the unification: one mapping format, one
parser signature, one kernel, and per-workflow orchestration where it is
genuinely different.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import EntityRule, Mapping, PropertyRule

_EMPTY = (None, "", [], {})


@dataclass
class Record:
    """A source record queued for mapping: its data + the entity rule matched."""

    data: dict
    rule: EntityRule
    source_id: str = ""


class Context:
    """Mutable conversion state passed to every parser and hook.

    ``extras`` is the plugin scratchpad (guid maps, fallback agents, association
    indexes, …). ``node`` / ``node_extras`` are set by the engine per record so
    parsers can reach the record being mapped and stash side outputs.
    """

    def __init__(self, plugin, direction: str, source):
        self.plugin = plugin
        self.mapping: Mapping = plugin.mapping
        self.direction = direction          # "import" | "export"
        self.source = source
        self.by_id: dict = {}
        self.root: dict = {}
        self.records: list[Record] = []
        self.out_nodes: dict = {}
        self.order: list = []
        self.extras: dict = {}
        self.node: dict = {}
        self.node_extras: dict = {}


# ============================================================================
# Templates
# ============================================================================

_TOKEN = re.compile(r"\{([^{}]+)\}")


def interpolate(template: str, tokens: dict) -> str:
    """Replace ``{token}`` with ``tokens[token]`` (unknown tokens left as-is)."""
    def sub(m):
        key = m.group(1)
        return str(tokens.get(key, m.group(0)))
    return _TOKEN.sub(sub, template)


# ============================================================================
# Parser application
# ============================================================================

def run_import_parser(ctx: Context, rule: PropertyRule, value):
    parser = ctx.plugin.import_parsers[rule.import_parser]
    return parser(value, rule, ctx)


def run_export_parser(ctx: Context, rule: PropertyRule, value):
    parser = ctx.plugin.export_parsers[rule.export_parser]
    return parser(value, rule, ctx)


def _read_source(record: dict, rule: PropertyRule):
    if rule.source_property:
        return record.get(rule.source_property)
    return None


def apply_import_rules(record: dict, rules: list[PropertyRule], ctx: Context) -> dict:
    """Apply import rules to one source record. First rule to set a target wins.

    A rule whose value is empty falls back to ``fallback_source`` (+
    ``fallback_parser``) when given. ``constant_value`` is interpolated against
    the record. Side outputs a parser stashes in ``ctx.node_extras`` (e.g.
    ``parameters``) are merged in at the end. This is the wrroc / c2m2 /
    croissant semantics; d4d composes rules itself (many-to-one merge).
    """
    out: dict = {}
    ctx.node = record
    ctx.node_extras = {}
    for rule in rules:
        target = rule.target_property
        if out.get(target) not in _EMPTY:
            continue
        if rule.source_property is None and rule.constant_value:
            result = interpolate(rule.constant_value, record)
        else:
            result = run_import_parser(ctx, rule, _read_source(record, rule))
            if result is None and rule.fallback_source:
                fb_value = record.get(rule.fallback_source)
                result = ctx.plugin.import_parsers[
                    rule.fallback_parser or rule.import_parser](fb_value, rule, ctx)
        if result is not None:
            out[target] = result
    for k, v in ctx.node_extras.items():
        out.setdefault(k, v)
    return out


def apply_export_rules(node: dict, rules: list[PropertyRule], ctx: Context) -> dict:
    """Apply export rules to one target-side node. First rule to set wins."""
    out: dict = {}
    ctx.node = node
    for rule in rules:
        target = rule.source_property
        if not target or out.get(target) not in _EMPTY:
            continue
        result = run_export_parser(ctx, rule, node.get(rule.target_property))
        if result is not None:
            out[target] = result
    return out


# ============================================================================
# Pipeline driver (wrroc / c2m2 / croissant)
# ============================================================================

def _default_select_rules(ctx: Context, rec: Record) -> list[PropertyRule]:
    """Default rule set for a record: grouped by the fairscape-side entity.

    Import: every rule producing this record's target type (several source types
    can share one target's rule set — wrroc Software). Export: every rule reading
    this record's kind. A plugin whose rules key on the source instead overrides
    via ``hooks['select_rules']`` (e.g. by-table selection).
    """
    if ctx.direction == "import":
        return ctx.mapping.import_rules_by_target(rec.rule.target_type)
    return ctx.mapping.export_rules_by_target(rec.rule.target_type)


def _default_resolve_id(ctx: Context, rec: Record) -> str:
    """Default ``@id`` for a mapped node.

    Honours a precomputed ``ctx.extras['guid_map']`` (wrroc mints ARKs up front);
    otherwise applies the entity rule's ``id_strategy`` for the simple cases.
    """
    guid_map = ctx.extras.get("guid_map")
    if guid_map and rec.source_id in guid_map:
        return guid_map[rec.source_id]
    rule = rec.rule
    if rule.id_strategy in ("keep", "column"):
        return rec.source_id
    if rule.id_template:
        return interpolate(rule.id_template, rec.data)
    return rec.source_id


def _default_map_record(ctx: Context, rec: Record, rules: list[PropertyRule]):
    """Default per-record mapper: apply the CSV property rules, stamp ``@type``
    and the round-trip ``identifier``.

    A plugin overrides this (``hooks['map_record']``) when one record does not
    map rule-by-rule — c2m2's vars pipeline, d4d's many-to-one merge. An
    override may set ``@id`` itself and may return ``None`` to drop the record.
    """
    if ctx.direction == "import":
        node = apply_import_rules(rec.data, rules, ctx)
    else:
        node = apply_export_rules(rec.data, rules, ctx)
    if rec.rule.target_type_iri:
        node["@type"] = (rec.rule.target_type_iri if len(rec.rule.target_type_iri) > 1
                         else rec.rule.target_type_iri[0])
    if ctx.direction == "import" and rec.rule.keep_identifier and rec.source_id:
        node["identifier"] = rec.source_id
    return node


def run_pipeline(plugin, direction: str, source, options: dict | None = None):
    """Drive a pipeline-style conversion: pre -> map (engine) -> link -> assemble.

    The plugin's ``pre`` hook fills ``ctx.records`` (and any indexes in
    ``ctx.extras``); the engine maps each record with its rule set via
    ``map_record``; ``link`` adds cross-node edges; ``assemble`` builds and
    returns the final object. Per-run options (e.g. ``naan``, ``validate``) are
    seeded into ``ctx.extras``.

    A record whose mapping returns ``None`` is dropped. On a duplicate ``@id``
    the first-mapped node wins (later records are skipped) — ``pre`` may seed
    ``ctx.out_nodes``/``ctx.order`` to reserve ids ahead of the loop.
    """
    ctx = Context(plugin, direction, source)
    if options:
        ctx.extras.update(options)
    plugin.hook("pre")(ctx)

    select_rules = plugin.hooks.get("select_rules", _default_select_rules)
    resolve_id = plugin.hooks.get("resolve_id", _default_resolve_id)
    map_record = plugin.hooks.get("map_record", _default_map_record)

    for rec in ctx.records:
        node = map_record(ctx, rec, select_rules(ctx, rec))
        if node is None:
            continue
        node.setdefault("@id", resolve_id(ctx, rec))
        if node["@id"] in ctx.out_nodes:      # first writer wins
            continue
        ctx.out_nodes[node["@id"]] = node
        ctx.order.append(node["@id"])

    plugin.hook("link")(ctx)
    return plugin.hook("assemble")(ctx)
