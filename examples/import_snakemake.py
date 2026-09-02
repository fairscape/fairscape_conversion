#!/usr/bin/env python3
"""Use case: a Snakemake pipeline finished and you want its provenance.

``snakemake --reporter fairscape`` (the snakemake-report-plugin-fairscape
reporter) hands the finished DAG over as plain records — one entry per job,
per rule and per file. That reporter owns the Snakemake and filesystem I/O;
this package owns the mapping, so the conversion below is a pure function you
can run on records captured anywhere.

The example input is a three-rule chain (``plugins/snakemake/input.json``).

    python examples/import_snakemake.py
"""

import _example as ex

ex.banner("Snakemake run records -> EVI RO-Crate",
          have="the records JSON from `snakemake --reporter fairscape`",
          want="each job as an EVI Computation in a dependency chain")

records = ex.read(ex.PLUGINS / "snakemake" / "input.json")
print(f"{len(records['jobs'])} job(s) from rule(s) "
      + ", ".join(sorted(records["rules"]))
      + f"; {len(records['files'])} file(s)")

crate = ex.plugin("snakemake").convert("import", records)

ex.summarize(crate)
ex.show_provenance(crate)

ex.write(crate, ex.OUT / "snakemake" / "ro-crate-metadata.json")
ex.check_golden(crate, "snakemake")
