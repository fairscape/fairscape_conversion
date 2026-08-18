#!/usr/bin/env python3
"""c2m2 plugin — CFDE C2M2 Frictionless datapackage -> FAIRSCAPE RO-Crate.

Import-only and self-contained. The plugin class is ``impl.C2m2Plugin``: the
mapping is the unified CSVs in this folder; the workflow machinery
(datapackage reflection, CV/ontology resolution, joins, preservation,
provenance, root) is the plugin-local ``mapper`` / ``parsers`` / ``ontology``
modules. The original ``c2m2-rocrate`` converter is untouched and serves only
as the parity-test reference.

    convert("import", "/path/to/datapackage-dir") -> rocrate dict
"""

from __future__ import annotations

from .impl import C2m2Plugin

PLUGIN = C2m2Plugin()


def convert(direction: str, datapackage_dir, output_path=None, **kwargs) -> dict:
    """Convert a C2M2 datapackage directory into an RO-Crate dict (import only).

    Writes ``ro-crate-metadata.json`` + the preserved source files into
    ``output_path`` (default: ``<dir>/<dcc>-c2m2-crate``) and returns the crate.
    """
    if direction != "import":
        raise ValueError("c2m2 is import-only (C2M2 -> RO-Crate)")
    return PLUGIN.convert("import", datapackage_dir, output_path=output_path, **kwargs)
