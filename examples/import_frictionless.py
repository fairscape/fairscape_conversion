#!/usr/bin/env python3
"""Use case: a dataset already described as a Frictionless Data Package.

A ``datapackage.json`` names the files and, for tables, types every column
(a Table Schema). Each resource becomes an EVI Dataset and each Table
Schema an EVI Schema the Dataset points at — constraints, keys and
missing-value markers included — so the crate can validate the files.

The example input is a small surveillance package
(``plugins/frictionless/input-datapackage/``): weekly county case counts,
a county reference table with a foreign key, and a remote methods PDF.

    python examples/import_frictionless.py
"""

import _example as ex

ex.banner("Frictionless Data Package -> EVI RO-Crate",
          have="a folder with datapackage.json (and its CSVs)",
          want="a Dataset per resource, a tabular Schema per Table Schema")

package = ex.PLUGINS / "frictionless" / "input-datapackage"
print(f"package: {package.name}/")

crate = ex.plugin("frictionless").convert("import", package, crate_dir=package)

ex.summarize(crate)
ex.show_provenance(crate)

for node in crate["@graph"]:
    if "Schema" not in str(node.get("@type")):
        continue
    print(f"\n{node['name']}: {len(node['properties'])} columns, "
          f"required {node.get('required')}, primary key {node.get('primaryKey')}")
    for name, prop in node["properties"].items():
        extra = prop.get("enum") or prop.get("pattern") or prop.get("source-type") or ""
        print(f"  {name:<16} {prop['type']:<8} {prop['description'][:40]:<40} {extra}")

ex.write(crate, ex.OUT / "frictionless" / "ro-crate-metadata.json")
ex.check_golden(crate, "frictionless")
