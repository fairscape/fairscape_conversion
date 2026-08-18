#!/usr/bin/env python3
"""Croissant plugin registries — names the CSVs reference resolve to the SAME
functions and classes the production ``fairscape_models`` converter uses, so the
reconstructed mapping is behaviour-identical.

The parser/builder cells in a Python-dict mapping were function *objects*; the
unified format needs them by name. This module is that name -> object registry.
Everything is imported from the production converter (never reimplemented), so
this plugin is a faithful CSV skin over the existing engine.
"""

from __future__ import annotations

from fairscape_models.conversion.mapping import croissant as _c
from fairscape_models.conversion.mapping import utils as _u
from fairscape_models.conversion.models import (CroissantDataset,
                                                CroissantFileObject,
                                                DEFAULT_CROISSANT_CONTEXT)

# source_key parsers (fn(value) -> value)
PARSERS = {
    "format_name": _u.format_name,
    "parse_cite_as": _u.parse_cite_as,
    "parse_authors_to_person_list": _u.parse_authors_to_person_list,
    "parse_publisher": _u.parse_publisher,
    "format_md5": _u.format_md5,
    "map_schema_type_to_croissant_data_type": _u.map_schema_type_to_croissant_data_type,
    "map_format_to_mime_type": _c.map_format_to_mime_type,
    # the inline file-@id lambda, now a named function
    "croissant_file_id": lambda x: _u.ro_crate_id_to_croissant_local_id(x, prefix="file-"),
}

# whole-entity builders (fn(converter_instance=, source_entity_model=))
BUILDERS = {
    "record_sets": _c.build_croissant_record_sets,
    "personal_sensitive": _c._build_personal_sensitive_info,
    "rai": _c._build_rai_property,        # used via functools.partial with CSV params
}

TARGET_CLASSES = {
    "CroissantDataset": CroissantDataset,
    "CroissantFileObject": CroissantFileObject,
}

CONTEXT = {"@DEFAULT_CROISSANT_CONTEXT": DEFAULT_CROISSANT_CONTEXT}

# Names the loader validates against (parsers + the builder: pseudo-names).
_BUILDER_TOKENS = {"builder:none", "builder:record_sets", "builder:rai",
                   "builder:personal_sensitive"}
EXPORT_PARSERS = {**{k: v for k, v in PARSERS.items()},
                  **{t: None for t in _BUILDER_TOKENS}}
IMPORT_PARSERS: dict = {}
