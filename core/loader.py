#!/usr/bin/env python3
"""Read a plugin's CSVs directly into a ``Mapping`` (no compiled artifact).

The CSVs are the single source of truth — there is no build step and no
generated JSON to drift. Parser-name validation happens here, at load time: a
name in ``import_parser`` / ``export_parser`` that no registered parser
implements raises ``ValueError`` before any conversion runs.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .schema import (AssocRule, CvBase, EntityRule, Mapping, PropertyRule,
                     split_pipe)


def _read(path: Path) -> list[dict]:
    """Rows of a CSV as dicts; skips fully blank rows. Missing file -> []."""
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def _b(cell: str) -> bool:
    return (cell or "").strip().upper() == "TRUE"


def _s(row: dict, key: str) -> str:
    return (row.get(key) or "").strip()


def load_mapping(mapping_dir: Path,
                 import_parser_names: set[str] | None = None,
                 export_parser_names: set[str] | None = None) -> Mapping:
    """Load ``entities.csv`` (+ optional properties/associations/cv_bases)."""
    mapping_dir = Path(mapping_dir)
    m = Mapping()

    for row in _read(mapping_dir / "entities.csv"):
        m.entities.append(EntityRule(
            source_type=_s(row, "source_type"),
            discriminator=_s(row, "discriminator") or None,
            target_type=_s(row, "target_type") or None,
            target_type_iri=split_pipe(_s(row, "target_type_iri")),
            level=_s(row, "level"),
            id_strategy=_s(row, "id_strategy") or "mint",
            id_template=_s(row, "id_template"),
            id_column=_s(row, "id_column"),
            keep_identifier=_b(_s(row, "keep_identifier")),
            mint_prefix=_s(row, "mint_prefix"),
            precedence=int(_s(row, "precedence")) if _s(row, "precedence") else 0,
            note=_s(row, "note"),
        ))

    for row in _read(mapping_dir / "properties.csv"):
        rule = PropertyRule(
            source_type=_s(row, "source_type"),
            source_property=_s(row, "source_property") or None,
            target_type=_s(row, "target_type"),
            target_property=_s(row, "target_property"),
            import_parser=_s(row, "import_parser"),
            export_parser=_s(row, "export_parser"),
            direction=_s(row, "direction") or "both",
            reverse_primary=_b(_s(row, "reverse_primary")),
            requirement=_s(row, "requirement"),
            cardinality=_s(row, "cardinality") or "scalar",
            constant_value=_s(row, "constant_value"),
            fallback_source=_s(row, "fallback_source"),
            fallback_parser=_s(row, "fallback_parser"),
            source_table=_s(row, "source_table"),
            param_name=_s(row, "param_name"),
            wrap=_s(row, "wrap"),
            note=_s(row, "note"),
        )
        _validate_parsers(rule, import_parser_names, export_parser_names)
        m.properties.append(rule)

    for row in _read(mapping_dir / "associations.csv"):
        m.associations.append(AssocRule(
            source_type=_s(row, "source_type"),
            assoc_table=_s(row, "assoc_table"),
            match_columns=split_pipe(_s(row, "match_columns")),
            match_resolver=_s(row, "match_resolver"),
            value_columns=split_pipe(_s(row, "value_columns")),
            value_resolver=_s(row, "value_resolver"),
            value_entity=_s(row, "value_entity"),
            target_property=split_pipe(_s(row, "target_property")),
            wrap=_s(row, "wrap") or "ident_ref",
            filter_column=_s(row, "filter_column"),
            filter_endswith=_s(row, "filter_endswith"),
            param_name=_s(row, "param_name"),
            note=_s(row, "note"),
        ))

    for row in _read(mapping_dir / "cv_bases.csv"):
        m.cv_bases.append(CvBase(
            key=_s(row, "key"),
            kind=_s(row, "kind") or "curie",
            iri_base=_s(row, "iri_base"),
            ontology_name=_s(row, "ontology_name"),
            curie_prefix=_s(row, "curie_prefix"),
            note=_s(row, "note"),
        ))

    return m


def _validate_parsers(rule: PropertyRule,
                      import_names: set[str] | None,
                      export_names: set[str] | None):
    """A parser name a plugin never registered is a typo — fail loud, fail early."""
    where = f"{rule.source_type}.{rule.source_property or '(synth)'}"
    if (import_names is not None and rule.direction in ("both", "import")
            and rule.import_parser and rule.import_parser not in import_names):
        raise ValueError(f"unknown import_parser {rule.import_parser!r} for {where}")
    if (export_names is not None and rule.direction in ("both", "export")
            and rule.export_parser and rule.export_parser not in export_names
            and rule.export_parser != "drop_export"):
        raise ValueError(f"unknown export_parser {rule.export_parser!r} for {where}")
