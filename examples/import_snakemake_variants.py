#!/usr/bin/env python3
"""Use case: a real Snakemake pipeline finished and you want its provenance.

Same conversion as ``import_snakemake.py``, but on a real run instead of a
fixture: ``snakemake-variant-calling/`` aligns three samples' reads to a
reference with bwa-mem, sorts and indexes them with samtools, calls variants
across all three with bcftools, and summarises the calls. Twelve jobs over six
rules, each in its own conda environment — the run is reproduced by
``snakemake-variant-calling/run.sh``, which is also where the checked-in crate
came from.

The input here is the records file that run left behind
(``snakemake-variant-calling/run/records.json``, written by
``snakemake --reporter fairscape``). The conversion is a pure function over
it, so this runs in a fraction of a second and needs no Snakemake.

    python examples/import_snakemake_variants.py
"""

from pathlib import Path

import _example as ex

RUN = Path(__file__).resolve().parent / "snakemake-variant-calling"

ex.banner("A real Snakemake run -> EVI RO-Crate",
          have="the records `snakemake --reporter fairscape` wrote for a "
               "variant-calling run",
          want="every job as an EVI Computation, every file as a Dataset")

records = ex.read(RUN / "run" / "records.json")
print(f"{len(records['jobs'])} job(s) over {len(records['rules'])} rule(s) "
      f"({', '.join(sorted(records['rules']))}), "
      f"{len(records['files'])} file(s), "
      f"{len(records['schemas'])} inferred schema(s)")

crate = ex.plugin("snakemake").convert("import", records)

ex.summarize(crate)
ex.show_provenance(crate, limit=18)

ex.write(crate, ex.OUT / "snakemake-variants" / "ro-crate-metadata.json")

# The crate checked in beside the workflow is this same conversion, plus the
# inverse EVI links fairscape-cli adds afterwards — so the entities have to
# line up one for one.
ex.check_same_entities(crate, RUN / "ro-crate-metadata.json")
