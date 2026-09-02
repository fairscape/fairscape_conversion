#!/usr/bin/env python3
"""Common Provenance Model (CPM) RO-Crate <-> FAIRSCAPE EVI RO-Crate.

CPM (ISO/TS 23494; Wittner et al. 2022, https://pmc.ncbi.nlm.nih.gov/articles/
PMC9383664/) documents provenance split across organizations: each org writes
its part as a W3C PROV bundle in a standalone file, and the CPM RO-Crate
profile (https://by-covid.github.io/cpm-ro-crate/) registers those files in a
crate as ``CPMProvenanceFile`` entries. Import parses the bundles (PROV-N or
PROV-JSON) and stitches them into one EVI graph; export writes an EVI crate's
provenance back out as a PROV document.

    from fairscape_conversion.plugins import cpm
    crate      = cpm.convert("import", "path/to/crate-dir")
    provjson   = cpm.convert("export", crate)                       # PROV-JSON
    provn_text = cpm.convert("export", crate, serialization="provn")
"""

from .hooks import CpmPlugin

PLUGIN = CpmPlugin()


def convert(direction, source, **options):
    return PLUGIN.convert(direction, source, **options)
