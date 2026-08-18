#!/usr/bin/env python3
"""wrroc plugin — Workflow Run RO-Crate <-> FAIRSCAPE EVI RO-Crate.

The plugin class is ``hooks.WrrocPlugin``: import (WRROC -> EVI) runs the
shared pipeline with a full-control ``pre`` (classification + ARK minting
interleave) and named discriminators; export (EVI -> Process Run Crate) is a
bespoke ``export`` override. Both read the same ``entities.csv`` +
``properties.csv``.

    convert("import", wrroc_crate) -> evi_crate
    convert("export", evi_crate)   -> process_run_crate
"""

from __future__ import annotations

from .hooks import WrrocPlugin
from .parsers import DEFAULT_NAAN

PLUGIN = WrrocPlugin()


def convert(direction: str, source: dict, naan: str = DEFAULT_NAAN, validate: bool = True) -> dict:
    if direction == "import":
        return PLUGIN.convert("import", source, naan=naan, validate=validate)
    return PLUGIN.convert(direction, source)


# Convenience aliases matching the original module names.
def to_evi(crate, naan=DEFAULT_NAAN, validate=True):
    return convert("import", crate, naan=naan, validate=validate)


def to_wrroc(crate):
    return convert("export", crate)
