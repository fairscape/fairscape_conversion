#!/usr/bin/env python3
"""Turn the metadata Cromwell wrote into an RO-Crate (step 2 of run.sh).

The cromwell plugin does the file reading itself: ``extract.py`` resolves the
call graph out of metadata.json, writes the submitted WDL and inputs JSON into
the crate, and decides for every path whether it is a file inside the crate (a
relative ``contentUrl``) or somewhere else on this machine (``localPath``).
``crate_dir`` is what anchors that decision, so it is the one option you
always want to pass.

Then fairscape-cli, if it is installed, derives the same companion artifacts
the Snakemake reporter derives automatically: the inverse EVI links, the
provenance graph, the D4D/LinkML export, the datasheet and the AI-ready
score. The Croissant export is its own example: ../export_croissant_variants.py.
"""

import json
from pathlib import Path

from fairscape_conversion.plugins import cromwell

HERE = Path(__file__).resolve().parent
CRATE = HERE / "ro-crate-metadata.json"

crate = cromwell.convert(
    "import", str(HERE / "run" / "metadata.json"),
    crate_dir=str(HERE),
    name="Variant calling on three sequenced samples (WDL)",
    description="Reads from three samples aligned with bwa-mem in a scatter, "
                "sorted and indexed with samtools, then jointly called with "
                "bcftools; a Cromwell run captured as an EVI RO-Crate.",
    author="Example Researcher",
    keywords="cromwell, wdl, variant calling, bwa, bcftools, genomics",
    schemas=True,
)
CRATE.write_text(json.dumps(crate, indent=4, default=str) + "\n")
print(f"{len(crate['@graph'])} nodes written to {CRATE.name}")

try:
    from fairscape_cli.utils.build_utils import process_crate
except ImportError:
    print("fairscape-cli not installed; skipping the datasheet and the "
          "provenance graph")
else:
    results = process_crate(HERE, link_inverses=True, add_io=True,
                            evidence_graph=True, linkml=True, datasheet=True,
                            preview=True, force=True)
    for error in results.get("errors", []):
        print(f"WARNING: {error}")
