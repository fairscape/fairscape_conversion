#!/usr/bin/env python3
"""Use case: a Cromwell/WDL workflow finished and you want its provenance.

Cromwell already wrote down every call it made — ``cromwell run -m
metadata.json`` (or ``GET /api/workflows/v1/{id}/metadata``) leaves a file
with each job's command, container, inputs, outputs and timings. This turns
that record into an EVI crate without re-running anything.

The example input is a pre-extracted records dict (a scatter workflow,
``plugins/cromwell/input.json``) so the example stays hermetic. Against a real
run you pass the metadata file itself and ``extract.py`` reads it for you:

    from fairscape_conversion.plugins import cromwell
    cromwell.convert("import", "metadata.json", crate_dir="./crate")

Run this example:

    python examples/import_cromwell.py
"""

import _example as ex

ex.banner("Cromwell run metadata -> EVI RO-Crate",
          have="the metadata.json a finished Cromwell run wrote",
          want="every task call as an EVI Computation, files linked to it")

records = ex.read(ex.PLUGINS / "cromwell" / "input.json")
print(f"workflow '{records['run']['name']}' — {len(records['jobs'])} job(s) "
      f"over {len(records['tasks'])} task(s), {len(records['files'])} file(s)")

crate = ex.plugin("cromwell").convert("import", records)

ex.summarize(crate)
ex.show_provenance(crate)

ex.write(crate, ex.OUT / "cromwell" / "ro-crate-metadata.json")
ex.check_golden(crate, "cromwell")
