#!/usr/bin/env python3
"""PluginBase — subclass this to add a converter.

A converter is a folder of CSVs (the mapping data, see ``MAPPING-SCHEMA.md``)
plus one subclass of :class:`PluginBase` (the workflow's code). The base class
exposes the exact surface ``run_pipeline`` drives (``mapping`` /
``import_parsers`` / ``export_parsers`` / ``hooks`` / ``hook()``), so an
instance is a drop-in for the old ``Plugin`` dataclass and the engine itself
never changes.

You override plain methods; your IDE lists them all. The import pipeline runs

    pre -> (per record) select_rules / map_record / resolve_id -> link -> assemble

and the default ``pre`` is just ``setup()`` + ``load_source()`` + ``classify()``,
so the common case is: write ``load_source`` (turn your format into
``SourceRecord``s, ~10 lines with the ``core.records`` helpers) and
``assemble`` (wrap the mapped nodes into the final document). Everything else
defaults to the engine's generic behaviour. See ``docs/NEW-PLUGIN.md`` for the
start-to-finish walkthrough and ``plugins/example/`` for a runnable minimal
plugin.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Iterable, Optional

from .engine import (Context, Record, _default_map_record, _default_resolve_id,
                     _default_select_rules, run_pipeline)
from .loader import load_mapping
from .records import SourceRecord, classify_node
from .schema import EntityRule, Mapping, PropertyRule


class PluginBase:
    """One converter: its CSV mapping + the named code the CSVs reference.

    Subclass checklist (see docs/NEW-PLUGIN.md):

    1. Set ``name`` and the parser registries the CSVs name.
    2. Implement ``load_source`` (or override ``pre`` for full control).
    3. Implement ``assemble``.
    4. Optionally: ``discriminators``, ``setup``, ``link``, ``map_record``,
       or a wholesale ``export`` for bespoke reverse drivers.
    """

    # ---- class-level configuration (set these in the subclass) -------------
    name: str = ""
    #: Folder holding entities.csv / properties.csv; defaults to the
    #: subclass's own package folder.
    mapping_dir: Optional[Path] = None
    #: CSV ``import_parser`` name -> ``fn(value, rule, ctx)``.
    import_parsers: dict[str, Callable] = {}
    #: CSV ``export_parser`` name -> ``fn(value, rule, ctx)``.
    export_parsers: dict[str, Callable] = {}
    #: entities.csv ``discriminator`` name -> ``fn(node, ctx) -> bool``.
    discriminators: dict[str, Callable] = {}

    def __init__(self) -> None:
        if self.mapping_dir is None:
            self.mapping_dir = Path(sys.modules[type(self).__module__].__file__).parent
        # Loading here validates every parser name a CSV cell references, so a
        # typo fails at import time, not mid-conversion.
        self.mapping: Mapping = load_mapping(
            self.mapping_dir,
            import_parser_names=set(self.import_parsers),
            export_parser_names=set(self.export_parsers),
        )
        # The engine looks hooks up by stage name; binding them here keeps the
        # old hooks-dict contract while subclasses just override the methods.
        self.hooks: dict[str, Callable] = {
            "pre": self.pre,
            "select_rules": self.select_rules,
            "resolve_id": self.resolve_id,
            "map_record": self.map_record,
            "link": self.link,
            "assemble": self.assemble,
        }
        self.configure()

    def hook(self, stage: str, default: Callable = None) -> Callable:
        """The hook for ``stage`` (same accessor the old Plugin dataclass had)."""
        return self.hooks.get(stage, default if default is not None else (lambda ctx: None))

    def configure(self) -> None:
        """Run once after the mapping loads. Default: nothing.

        For one-time derived setup — e.g. c2m2 rebuilds its ontology lookup
        tables from ``cv_bases.csv`` here.
        """

    # ---- entry point --------------------------------------------------------
    def convert(self, direction: str, source, **options):
        """Convert ``source``. ``import`` = into a fairscape crate, ``export`` = out."""
        if direction == "import":
            return self.import_(source, options)
        if direction == "export":
            return self.export(source, options)
        raise ValueError(f"direction must be import|export, got {direction!r}")

    def import_(self, source, options: dict):
        """Source format -> fairscape crate, via the shared pipeline."""
        return run_pipeline(self, "import", source, options=options)

    def export(self, source, options: dict):
        """Fairscape crate -> source format.

        Default rides the engine in reverse. Override wholesale for a bespoke
        reverse driver (wrroc, d4d) or an engine bypass (croissant); raise for
        an import-only plugin.
        """
        return run_pipeline(self, "export", source, options=options)

    # ---- import pipeline steps (override as needed) --------------------------
    def setup(self, ctx: Context) -> None:
        """Build indexes / mint ids before any record is produced. Default: nothing.

        Stash whatever later steps need in ``ctx.extras`` (the plugin
        scratchpad); per-run options passed to ``convert`` are already there.
        """

    def load_source(self, source) -> Iterable[SourceRecord]:
        """Turn the raw input into candidate :class:`SourceRecord`s.

        The common case is one of the ``core.records`` helpers::

            return records_from_items({"memo": source["memos"]}, id_key="id")
            return records_from_graph(source["@graph"])

        Give each record a ``source_type`` when you know which entities.csv row
        it belongs to; leave it ``""`` to classify by the node's ``@type``.
        """
        return []

    def classify(self, ctx: Context, sr: SourceRecord) -> Optional[EntityRule]:
        """The entities.csv rule for one source record (``None`` drops it).

        Default: first matching row in CSV order, gating on this plugin's
        named ``discriminators``.
        """
        return classify_node(sr, ctx.mapping.entities, ctx, self.discriminators)

    def pre(self, ctx: Context) -> None:
        """Fill ``ctx.records`` (stage 1 of the pipeline).

        Default: ``setup()``, then classify everything ``load_source()`` yields.
        Override for full control when loading and classification interleave
        (wrroc's ARK minting, c2m2's table reflection).
        """
        self.setup(ctx)
        records = []
        for sr in self.load_source(ctx.source):
            rule = self.classify(ctx, sr)
            if rule is not None:
                records.append(Record(data=sr.data, rule=rule, source_id=sr.source_id))
        ctx.records = records

    def select_rules(self, ctx: Context, rec: Record) -> list[PropertyRule]:
        """The properties.csv rules for one record. Default: all rules for the
        record's fairscape-side target type."""
        return _default_select_rules(ctx, rec)

    def resolve_id(self, ctx: Context, rec: Record) -> str:
        """The ``@id`` for a mapped node. Default: ``ctx.extras['guid_map']``
        if seeded, else the entity rule's ``id_strategy``."""
        return _default_resolve_id(ctx, rec)

    def map_record(self, ctx: Context, rec: Record, rules: list[PropertyRule]):
        """One record -> one output node (``None`` drops it). Default: apply the
        CSV property rules and stamp ``@type``. Override when a record does not
        map rule-by-rule (d4d's many-to-one merge, c2m2's vars pipeline)."""
        return _default_map_record(ctx, rec, rules)

    def link(self, ctx: Context) -> None:
        """Add cross-node edges once every node exists. Default: nothing."""

    def assemble(self, ctx: Context):
        """Build and return the final document from ``ctx.out_nodes`` /
        ``ctx.order``. Every real plugin implements this."""
        raise NotImplementedError(f"{type(self).__name__} must implement assemble()")
