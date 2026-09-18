#!/usr/bin/env python3
"""Use case: deposit a crate somewhere that speaks Data Package.

Any EVI crate exports: the root becomes the package, each Dataset a
resource, and a Dataset's ``evi:Schema`` a Table Schema with its
constraints, keys and missing-value markers. Provenance nodes (Computation,
Software) have no Data Package home and are left out.

Shown on the crate the redcap example makes, so the Table Schema below is a
REDCap codebook re-expressed for a Frictionless-aware repository.

    python examples/export_frictionless.py
"""

import json

import _example as ex

ex.banner("EVI RO-Crate -> Frictionless Data Package",
          have="an EVI crate with Datasets and tabular Schemas",
          want="a datapackage.json with a Table Schema per tabular Dataset")

crate = ex.read(ex.PLUGINS / "redcap" / "golden.json")
print(f"crate: {crate['@graph'][1]['name']} ({len(crate['@graph'])} nodes)")

package = ex.plugin("frictionless").convert("export", crate)

print(f"\npackage '{package['name']}' ({package['profile']}): {len(package['resources'])} resource(s)")
for res in package["resources"]:
    fields = res.get("schema", {}).get("fields", [])
    print(f"  {res['name']:<28} {res.get('format', ''):<6} {res.get('path', '')}"
          + (f"  ({len(fields)} typed fields)" if fields else ""))
tabular = next(r for r in package["resources"] if "schema" in r)
for field in tabular["schema"]["fields"][:6]:
    print(f"    {field['name']:<14} {field['type']:<8} {json.dumps(field.get('constraints', {}))}")

ex.write(package, ex.OUT / "frictionless" / "datapackage.json")
