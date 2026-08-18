#!/usr/bin/env python3
"""d4d plugin — Datasheets for Datasets (D4D) <-> RO-Crate, bidirectional.

The canonical D4D bridge (supersedes the D4D path in
``fairscape_models/conversion``). Uses the unified entities/properties CSVs.
The plugin class is ``impl.D4dPlugin``: import rides the shared pipeline
(d4d's many-to-one merge is its ``map_record`` override), export is a bespoke
reverse driver (its ``export`` override).

    convert("import", d4d_dict) -> rocrate
    convert("export", rocrate)  -> d4d_dict
"""

from __future__ import annotations

from .impl import D4dPlugin

PLUGIN = D4dPlugin()


def convert(direction: str, source: dict, validate: bool = True) -> dict:
    return PLUGIN.convert(direction, source, validate=validate)
