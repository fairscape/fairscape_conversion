#!/usr/bin/env python3
"""Dataclasses for the unified converter mapping.

These mirror the CSV columns documented in ``fairscape_conversion/MAPPING-SCHEMA.md`` one-to-one.
``loader.py`` turns the CSV rows into these objects; the engine and the plugins
read them. Nothing here knows about any particular workflow (wrroc, d4d, c2m2,
croissant) — it is the shared vocabulary they all speak.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def split_pipe(cell: str) -> list[str]:
    """A pipe-joined CSV cell -> list of tokens (blank cell -> [])."""
    return [p.strip() for p in cell.split("|") if p.strip()] if cell else []


@dataclass
class EntityRule:
    """One row of ``entities.csv`` — how a source record becomes a target node."""

    source_type: str
    discriminator: Optional[str] = None
    target_type: Optional[str] = None
    target_type_iri: list[str] = field(default_factory=list)
    level: str = ""
    id_strategy: str = "mint"
    id_template: str = ""
    id_column: str = ""
    keep_identifier: bool = False
    mint_prefix: str = ""
    precedence: int = 0
    note: str = ""


@dataclass
class PropertyRule:
    """One row of ``properties.csv`` — one property moved in one/both directions."""

    source_type: str
    source_property: Optional[str]
    target_type: str
    target_property: str
    import_parser: str = ""
    export_parser: str = ""
    direction: str = "both"
    reverse_primary: bool = False
    requirement: str = ""
    cardinality: str = "scalar"
    constant_value: str = ""
    fallback_source: str = ""
    fallback_parser: str = ""
    source_table: str = ""
    param_name: str = ""
    wrap: str = ""
    note: str = ""


@dataclass
class AssocRule:
    """One row of ``associations.csv`` — a join-table edge (c2m2)."""

    source_type: str
    assoc_table: str
    match_columns: list[str]
    match_resolver: str
    value_columns: list[str]
    value_resolver: str
    value_entity: str = ""
    target_property: list[str] = field(default_factory=list)
    wrap: str = "ident_ref"
    filter_column: str = ""
    filter_endswith: str = ""
    param_name: str = ""
    note: str = ""


@dataclass
class CvBase:
    """One row of ``cv_bases.csv`` — one controlled-vocabulary ontology base (c2m2).

    ``kind='curie'`` keys by the CURIE prefix as it appears in the TSV (``DOID``);
    ``kind='bare'`` keys by the CV table whose ids are bare accessions (``gene``),
    and then ``curie_prefix`` is the CURIE stem to reattach.
    """

    key: str
    kind: str = "curie"          # curie | bare
    iri_base: str = ""
    ontology_name: str = ""
    curie_prefix: str = ""
    note: str = ""


@dataclass
class Mapping:
    """The full compiled mapping for one plugin (all its CSVs)."""

    entities: list[EntityRule] = field(default_factory=list)
    properties: list[PropertyRule] = field(default_factory=list)
    associations: list[AssocRule] = field(default_factory=list)
    cv_bases: list[CvBase] = field(default_factory=list)

    # ---- convenience selectors the plugins use to pick a rule set -----------

    def entity_for(self, source_type: str) -> Optional[EntityRule]:
        for e in self.entities:
            if e.source_type == source_type:
                return e
        return None

    def import_rules_by_source(self, source_type: str) -> list[PropertyRule]:
        return [r for r in self.properties
                if r.source_type == source_type and r.direction in ("both", "import")
                and r.import_parser]

    def import_rules_by_target(self, target_type: str) -> list[PropertyRule]:
        return [r for r in self.properties
                if r.target_type == target_type and r.direction in ("both", "import")
                and r.import_parser]

    def export_rules_by_target(self, target_type: str) -> list[PropertyRule]:
        return [r for r in self.properties
                if r.target_type == target_type and r.direction in ("both", "export")
                and r.export_parser and r.export_parser != "drop_export"]

    def associations_for(self, source_type: str) -> list[AssocRule]:
        return [a for a in self.associations if a.source_type == source_type]

    def dropped_types(self) -> list[str]:
        return [e.source_type for e in self.entities if e.level == "drop"]

    def passthrough_properties(self) -> list[str]:
        return sorted({r.source_property for r in self.properties
                       if r.requirement == "passthrough" and r.source_property})
