#!/usr/bin/env python3
"""Turn the metadata Cromwell wrote into an RO-Crate (step 2 of run.sh).

The cromwell plugin does the file reading itself: ``extract.py`` resolves the
call graph out of metadata.json, writes the submitted WDL and inputs JSON into
the crate, and decides for every path whether it is a file inside the crate (a
relative ``contentUrl``) or somewhere else on this machine (``localPath``).
``crate_dir`` is what anchors that decision, so it is the one option you
always want to pass. ``schemas=True`` reads the tabular outputs and adds an
EVI Schema for each (``pip install "fairscape-conversion[schemas]"``).

Then the companion artifacts the Snakemake reporter derives automatically:
the D4D/LinkML datasheet is this package's own ``d4d`` export, and the inverse
EVI links, the inputs/outputs, the provenance graph, the datasheet and the
AI-ready review come from ``fairscape-artifacts`` when it is installed. The
Croissant export is its own example: ../export_croissant_variants.py.
"""

import json
import subprocess
import sys
from pathlib import Path

from fairscape_conversion.core.cli import _write
from fairscape_conversion.plugins import cromwell, d4d

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

_write(HERE / "ro-crate-linkml.yaml", d4d.convert("export", crate))
print("D4D datasheet written to ro-crate-linkml.yaml")

try:
    import fairscape_artifacts  # noqa: F401
except ImportError:
    print("fairscape-artifacts not installed; skipping the inverse links, the "
          "datasheet and the provenance graph (pip install fairscape-artifacts)")
else:
    for step in (["link-inverses"], ["add-io"], ["all"]):
        subprocess.run([sys.executable, "-m", "fairscape_artifacts", *step, str(HERE)],
                       check=True)
