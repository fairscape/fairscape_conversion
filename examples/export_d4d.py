#!/usr/bin/env python3
"""Use case: you have a crate and a reviewer wants a datasheet.

D4D is the one format here that runs both ways, so a crate built by any of the
importers can be handed back as a Datasheet for Datasets — the prose document
people actually read in review.

This exports the AI-READI crate (``plugins/d4d/golden.json``, itself the
output of ``import_d4d.py``) and then compares the result against the
datasheet that crate was built from, so you can see exactly what a round trip
does and does not preserve.

    python examples/export_d4d.py
"""

import json

import _example as ex

ex.banner("EVI RO-Crate -> D4D datasheet",
          have="an ro-crate-metadata.json",
          want="a datasheet YAML you can circulate for review")

d4d = ex.plugin("d4d")
crate = ex.read(ex.PLUGINS / "d4d" / "golden.json")
datasheet = d4d.convert("export", crate)

print(f"{len(datasheet)} sections out: {', '.join(sorted(datasheet))}")

original = ex.read(ex.PLUGINS / "d4d" / "input.yaml")


def _same(key):
    dump = lambda v: json.dumps(v, sort_keys=True, default=str)
    return key in datasheet and dump(original[key]) == dump(datasheet[key])


identical = [k for k in original if _same(k)]
dropped = [k for k in original if k not in datasheet or not datasheet[k]]
print(f"\nround trip: {len(identical)}/{len(original)} sections come back "
      f"byte-identical, {len(dropped)} come back empty or missing "
      f"{tuple(dropped) if dropped else ''}")
print("what changes:")
print("  - sub-entity ids ('aireadi:creator:1') are gone — the crate replaced")
print("    them with ARKs, and the ARK is what the export carries")
print(f"  - 'name' is the crate's full title, not the short handle "
      f"({original['name']!r} -> {datasheet['name'][:40]!r}...)")
print(f"  - the crate's own identity survives: id == {datasheet.get('id')}")

ex.write(datasheet, ex.OUT / "d4d" / "datasheet.yaml")
