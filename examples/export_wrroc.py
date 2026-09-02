#!/usr/bin/env python3
"""Use case: you have an EVI crate and a tool that speaks WRROC.

Workflow Run RO-Crate is the community profile most workflow tooling reads.
Exporting turns EVI's ``Computation`` / ``Dataset`` / ``Software`` back into
schema.org ``CreateAction``s with ``object``/``result`` — the same run, in the
vocabulary the other tools expect.

The input is the EVI crate ``import_wrroc.py`` produces, so this closes the
loop on the CWL revsort run.

    python examples/export_wrroc.py
"""

import _example as ex

ex.banner("EVI RO-Crate -> Workflow Run RO-Crate",
          have="an EVI crate with Computations",
          want="a WRROC crate of CreateActions for workflow tooling")

wrroc = ex.plugin("wrroc")
evi_crate = ex.read(ex.PLUGINS / "wrroc" / "golden.json")
computations = [n for n in evi_crate["@graph"] if "Computation" in str(n.get("@type"))]
print(f"{len(computations)} EVI Computation(s) in")

out = wrroc.convert("export", evi_crate)

actions = [n for n in out["@graph"] if "CreateAction" in str(n.get("@type"))]
print(f"{len(actions)} CreateAction(s) out")
for action in actions:
    objects = action.get("object") or []
    results = action.get("result") or []
    print(f"  {str(action.get('name'))[:44]:<46} "
          f"{len(objects)} object(s) -> {len(results)} result(s)")

ex.summarize(out)
ex.write(out, ex.OUT / "wrroc" / "wrroc-metadata.json")
