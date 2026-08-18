#!/usr/bin/env python3
"""Reconstruct the Croissant ``MAPPING_CONFIGURATION`` from the unified CSVs and
drive the production ``ROCToTargetConverter``.

Export-only (RO-Crate -> MLCommons Croissant). This is the D-compatibility
demonstration: the production ``fairscape_models`` converter is untouched and
imported as-is; only the *mapping* now comes from ``entities.csv`` +
``properties.csv`` instead of Python dicts. ``reconstruct_config`` produces a
configuration that drives that converter to byte-identical output (proven in
``test_croissant_parity``).
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from ...core import load_mapping
from .parsers import BUILDERS, CONTEXT, PARSERS, TARGET_CLASSES

HERE = Path(__file__).parent


def _mapping_def_for(mapping, source_type):
    """The spec-dict mapping_def for one source entity, from its property rows."""
    out = {}
    for r in mapping.properties:
        if r.source_type != source_type:
            continue
        tk = r.target_property
        parser = r.export_parser
        if parser.startswith("builder:"):
            b = parser[len("builder:"):]
            if b == "none":
                out[tk] = {"builder_func": None}
            elif b == "rai":
                names = r.param_name.split("|")
                additional = names if len(names) > 1 else names[0]
                out[tk] = {"builder_func": partial(
                    BUILDERS["rai"], rai_key=r.constant_value, additional_prop_name=additional)}
            else:
                out[tk] = {"builder_func": BUILDERS[b]}
        elif r.constant_value:
            out[tk] = {"fixed_value": CONTEXT.get(r.constant_value, r.constant_value)}
        else:
            spec = {"source_key": r.source_property}
            if parser:
                spec["parser"] = PARSERS[parser]
            out[tk] = spec
    return out


def reconstruct_config():
    """Unified CSVs -> the Croissant MAPPING_CONFIGURATION (entity_map etc.)."""
    mapping = load_mapping(HERE, export_parser_names=set(_export_names()))

    entity_map = {}
    for e in mapping.entities:
        if e.source_type == "Field":
            continue                                  # sub-mapping, handled below
        key = (e.source_type, e.discriminator or "COMPONENT")
        if e.target_type:
            entity_map[key] = {
                "target_class": TARGET_CLASSES[e.target_type],
                "mapping_def": _mapping_def_for(mapping, e.source_type),
            }
        else:
            entity_map[key] = None

    return {
        "entity_map": entity_map,
        "sub_mappings": {"field_mapping": _mapping_def_for(mapping, "Field")},
        "assembly_instructions": [{
            "child_type": TARGET_CLASSES["CroissantFileObject"],
            "parent_attribute": "distribution",
            "parent_type": TARGET_CLASSES["CroissantDataset"],
        }],
    }


def _export_names():
    from .parsers import EXPORT_PARSERS
    return set(EXPORT_PARSERS)


def convert(direction, crate):
    """RO-Crate dict -> Croissant dict (export only)."""
    if direction != "export":
        raise ValueError("croissant is export-only (RO-Crate -> Croissant)")
    from fairscape_models.conversion.converter import ROCToTargetConverter
    from fairscape_models.rocrate import ROCrateV1_2

    source = ROCrateV1_2.model_validate(crate)
    result = ROCToTargetConverter(source, reconstruct_config()).convert()
    return result.model_dump(by_alias=True, exclude_none=True) if result is not None else None
