#!/usr/bin/env python3
"""Use case: a real Cromwell/WDL workflow finished and you want its provenance.

Same conversion as ``import_cromwell.py``, but on a real run:
``wdl-variant-calling/`` is the same analysis as the Snakemake example written
as WDL — bwa-mem scattered over three samples, then samtools and a bcftools
gather — executed by Cromwell 92 on the local backend. Twelve calls, three of
them scatter shards.

Unlike the Snakemake plugin, this one reads the engine's own file: Cromwell's
``-m metadata.json`` already records every call's command, inputs, outputs and
timings, so ``extract.py`` goes straight at it. ``crate_dir`` tells the
extractor where the crate lives, which is what decides whether a path becomes
a relative ``contentUrl`` or a machine-specific ``localPath``.

    python examples/import_cromwell_variants.py
"""

from pathlib import Path

import _example as ex

RUN = Path(__file__).resolve().parent / "wdl-variant-calling"

ex.banner("A real Cromwell run -> EVI RO-Crate",
          have="the metadata.json Cromwell wrote for a variant-calling run",
          want="every call — scatter shards included — as an EVI Computation")

metadata = ex.read(RUN / "run" / "metadata.json")
calls = metadata["calls"]
print(f"workflow '{metadata['workflowName']}' finished {metadata['status']}: "
      f"{sum(len(v) for v in calls.values())} call(s) over "
      f"{len(calls)} task(s)")

crate = ex.plugin("cromwell").convert(
    "import", str(RUN / "run" / "metadata.json"),
    crate_dir=str(RUN),
    name="Variant calling on three sequenced samples (WDL)",
    description="Reads from three samples aligned with bwa-mem in a scatter, "
                "sorted and indexed with samtools, then jointly called with "
                "bcftools; a Cromwell run captured as an EVI RO-Crate.",
    author="Example Researcher",
    keywords="cromwell, wdl, variant calling, bwa, bcftools, genomics",
)

ex.summarize(crate)
ex.show_provenance(crate, limit=18)

ex.write(crate, ex.OUT / "cromwell-variants" / "ro-crate-metadata.json")

# Same conversion as the checked-in crate, minus the schema inference that
# reads the TSV and the inverse links fairscape-cli adds — so every entity
# except the Schema node has to line up.
ex.check_same_entities(crate, RUN / "ro-crate-metadata.json",
                       ignore_types=("Schema",))
