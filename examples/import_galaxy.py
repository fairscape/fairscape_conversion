#!/usr/bin/env python3
"""Use case: a Galaxy workflow ran and you want its provenance.

In Galaxy, *User → Workflow Invocations → Export* (or the API) writes an
invocation export. Its model store — ``invocation_attrs.txt``,
``jobs_attrs.txt``, ``datasets_attrs.txt``, ``collections_attrs.txt``, the
``.ga`` workflow — is what this reads: every job with its tool, version,
parameters, command line and exit code; every dataset (history copies of
one file collapsed) and collection; the uploads that made the inputs.

The example input is the WRROC spec's Galaxy collection-workflow export
(``plugins/galaxy/input-store/``).

    python examples/import_galaxy.py
"""

import _example as ex

ex.banner("Galaxy invocation export -> EVI RO-Crate",
          have="a Galaxy invocation export (archive or unpacked folder), or a .ga file",
          want="the invocation and each job as EVI Computations over the datasets")

store = ex.PLUGINS / "galaxy" / "input-store"
print(f"export: {store.name}/ (invocation_attrs.txt, jobs_attrs.txt, ...)")

crate = ex.plugin("galaxy").convert("import", store, author="Example Researcher", crate_dir=store)

ex.summarize(crate)
ex.show_provenance(crate, limit=40)

ex.write(crate, ex.OUT / "galaxy" / "ro-crate-metadata.json")
ex.check_golden(crate, "galaxy")
