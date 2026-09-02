#!/usr/bin/env python3
"""Use case: you want your dataset loadable from an ML data ecosystem.

MLCommons Croissant is what Hugging Face, Kaggle and TensorFlow Datasets read.
A crate that already carries EVI Schemas has everything Croissant needs — file
objects, record sets, and per-field types — so the export is a straight
re-serialization, no re-describing.

The input is deliberately the crate ``import_c2m2.py`` produces: a C2M2
datapackage becomes a crate becomes a Croissant document, which is the whole
point of having one hub format in the middle.

    python examples/export_croissant.py
"""

import _example as ex

ex.banner("EVI RO-Crate -> MLCommons Croissant",
          have="a crate whose Datasets carry EVI Schemas",
          want="a croissant.json an ML data loader can consume")

crate = ex.read(ex.PLUGINS / "croissant" / "input.json")
schemas = [n for n in crate["@graph"] if "Schema" in str(n.get("@type"))]
print(f"{len(crate['@graph'])} crate nodes in, {len(schemas)} of them Schemas")

croissant = ex.plugin("croissant").convert("export", crate)

distribution = croissant.get("distribution", [])
record_sets = croissant.get("recordSet", [])
print(f"\ncroissant '{croissant.get('name')}'")
print(f"  {len(distribution)} distribution entr(ies), {len(record_sets)} recordSet(s)")
for record_set in record_sets:
    fields = record_set.get("field", [])
    print(f"  recordSet {str(record_set.get('name'))[:40]:<42} {len(fields)} field(s)")

ex.write(croissant, ex.OUT / "croissant" / "croissant.json")
ex.check_golden(croissant, "croissant")
