#!/usr/bin/env python3
"""Source-shape helpers: turn raw input into records the engine can map.

A plugin's first job is loading its source format. Two common shapes get a
one-liner each:

* dict-of-lists  -> ``records_from_items({"biosample": rows, ...})``
* JSON-LD graph  -> ``records_from_graph(crate["@graph"])``

Classification — matching a record to its ``entities.csv`` row, including the
row's named ``discriminator`` predicate — lives here too (``classify_node``),
so a plugin only writes a predicate when its match genuinely needs one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from .schema import EntityRule

_EMPTY = (None, "", [], {})


@dataclass
class SourceRecord:
    """A candidate record before it is matched to an entity rule.

    ``source_type`` names the ``entities.csv`` row to match (table name, field
    name, …). Leave it ``""`` for graph-shaped sources: the record is then
    classified by its node's ``@type`` values instead.
    """

    data: dict
    source_type: str = ""
    source_id: str = ""


def types_of(node) -> list[str]:
    """A node's ``@type`` values as a list (empty if absent)."""
    t = node.get("@type") if isinstance(node, dict) else None
    if t in _EMPTY:
        return []
    return t if isinstance(t, list) else [t]


def classify_node(sr: SourceRecord, entities: list[EntityRule], ctx,
                  discriminators: dict[str, Callable]) -> Optional[EntityRule]:
    """The first ``entities.csv`` row that matches, in CSV order (precedence).

    A row matches when its ``source_type`` is the record's declared type (or
    one of the node's ``@type`` values for graph records) and its
    ``discriminator``, if any, names a registered predicate
    ``fn(node, ctx) -> bool`` that returns True. An unregistered discriminator
    name is a typo — fail loud, like the loader's parser-name check.
    Returns ``None`` when nothing matches (the record is dropped).
    """
    node = sr.data
    types = [sr.source_type] if sr.source_type else types_of(node)
    for rule in entities:
        if rule.source_type not in types:
            continue
        if rule.discriminator:
            pred = discriminators.get(rule.discriminator)
            if pred is None:
                raise ValueError(
                    f"unknown discriminator {rule.discriminator!r} for "
                    f"source_type {rule.source_type!r}; register it in the "
                    f"plugin's `discriminators` dict")
            if not pred(node, ctx):
                continue
        return rule
    return None


def records_from_items(items_by_type: dict, *, id_key: str = "@id") -> Iterator[SourceRecord]:
    """dict-of-lists source -> SourceRecords with a known ``source_type`` each.

    ``{"memo": [ {...}, ... ], "author": [...]}`` yields one record per item,
    typed by its key. A scalar dict value counts as a one-item list.
    """
    for source_type, items in items_by_type.items():
        if isinstance(items, dict):
            items = [items]
        for item in items or []:
            yield SourceRecord(item, source_type, str(item.get(id_key, "") or ""))


def records_from_graph(graph, *, skip_ids=("ro-crate-metadata.json",),
                       id_key: str = "@id") -> Iterator[SourceRecord]:
    """JSON-LD ``@graph`` source -> SourceRecords classified later by ``@type``.

    ``skip_ids`` drops bookkeeping nodes (the crate descriptor by default).
    """
    for node in graph:
        node_id = str(node.get(id_key, "") or "")
        if node_id in skip_ids:
            continue
        yield SourceRecord(node, "", node_id)
