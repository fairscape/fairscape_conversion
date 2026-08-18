#!/usr/bin/env python3
"""croissant plugin — FAIRSCAPE RO-Crate -> MLCommons Croissant (export-only).

The D-compatibility demonstration: the mapping is the unified entities/properties
CSVs, but the engine is the untouched production ``ROCToTargetConverter`` from
``fairscape_models.conversion``. Proves the unified format absorbs the
Python-dict spec converters without changing production code.

This is the worked example of an **engine-bypass plugin**: it overrides
``export`` wholesale and never touches the shared pipeline, yet still gets the
CSV loading + parser-name validation from ``PluginBase``.

    convert("export", rocrate_dict) -> croissant_dict
"""

from __future__ import annotations

from ...core import PluginBase
from . import impl
from .parsers import EXPORT_PARSERS, IMPORT_PARSERS


class CroissantPlugin(PluginBase):
    name = "croissant"
    import_parsers = IMPORT_PARSERS   # empty: export-only
    export_parsers = EXPORT_PARSERS   # includes the builder:* pseudo-tokens

    def import_(self, source, options: dict):
        raise ValueError("croissant is export-only (RO-Crate -> Croissant)")

    def export(self, source, options: dict):
        # Engine bypass: reconstruct the production converter's config from the
        # CSVs and let fairscape_models do the work (see impl.py).
        return impl.convert("export", source)


PLUGIN = CroissantPlugin()


def convert(direction: str, source: dict) -> dict:
    return PLUGIN.convert(direction, source)
