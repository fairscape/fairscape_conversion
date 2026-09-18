#!/usr/bin/env python3
"""Use case: you submitted (or received) a CFDE C2M2 datapackage.

C2M2 is the Common Fund Data Ecosystem's tabular interchange format: a
directory of TSVs plus ``C2M2_datapackage.json`` describing them. Everything a
crate needs is in there — files, biosamples, subjects, projects, and the
controlled-vocabulary terms tying them together — it just isn't linked data
yet. This walks the tables, resolves the CV terms to ontology IRIs, and emits
one EVI crate.

Unlike the other importers this one writes to disk: it copies the source TSVs
next to the crate so the result is self-contained, which is why it takes an
``output_path``.

    python examples/import_c2m2.py
"""

import os
import shutil

import _example as ex

ex.banner("C2M2 datapackage -> EVI RO-Crate",
          have="a directory of C2M2 TSVs + C2M2_datapackage.json",
          want="a self-contained crate with the tables preserved beside it")

work = ex.OUT / "c2m2"
shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)
shutil.copytree(ex.PLUGINS / "c2m2" / "input-datapackage", work / "input-datapackage")

tables = sorted(p.name for p in (work / "input-datapackage").glob("*.tsv"))
print(f"{len(tables)} table(s): {', '.join(tables)}")

# The converter records how it was invoked, so run it with relative paths from
# the working directory rather than baking an absolute path into the crate.
os.chdir(work)
crate = ex.plugin("c2m2").convert("import", "input-datapackage",
                                  output_path="c2m2-example-crate")

ex.summarize(crate)
ex.show_provenance(crate)

written = work / "c2m2-example-crate"
print(f"\nwrote {written.relative_to(ex.OUT.parent)}/ "
      f"({len(list(written.rglob('*')))} files: the crate + the preserved tables)")

# No golden check here: this crate carries today's date, the running
# fairscape_models version and the path it was invoked with, so it is
# machine- and day-specific by design.
