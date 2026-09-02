#!/usr/bin/env python3
"""Use case: a workflow engine already gave you a Workflow Run RO-Crate.

WRROC records what ran (``CreateAction``s, their inputs and outputs) in
schema.org terms. EVI records the same events as ``Computation`` /
``Dataset`` / ``Software`` with ARK identifiers, which is what the FAIRSCAPE
services index. This is the crate-to-crate translation between them.

The example input is a CWL revsort run (``plugins/wrroc/input.json``). WRROC
is bidirectional — ``export_wrroc.py`` goes the other way.

    python examples/import_wrroc.py
"""

import _example as ex

ex.banner("Workflow Run RO-Crate -> EVI RO-Crate",
          have="a WRROC ro-crate-metadata.json from your engine",
          want="the same run as EVI Computations with ARK ids")

wrroc = ex.read(ex.PLUGINS / "wrroc" / "input.json")
actions = [n for n in wrroc["@graph"] if "CreateAction" in str(n.get("@type"))]
print(f"{len(wrroc['@graph'])} nodes in, {len(actions)} CreateAction(s): "
      + ", ".join(str(a.get("name")) for a in actions))

# naan is your ARK Name Assigning Authority Number; 59853 is FAIRSCAPE's.
crate = ex.plugin("wrroc").convert("import", wrroc, naan="59853")

ex.summarize(crate)
ex.show_provenance(crate)

ex.write(crate, ex.OUT / "wrroc" / "ro-crate-metadata.json")
ex.check_golden(crate, "wrroc")
