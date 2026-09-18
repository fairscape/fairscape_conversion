#!/usr/bin/env python3
"""Use case: a REDCap project, and you want its codebook as a crate.

REDCap's *Data Dictionary → Download* gives you a CSV with one row per
field; *Data Exports → CSV (raw)* gives you the records. The dictionary
becomes an EVI tabular Schema of the export's columns (checkboxes expand,
each form gets a ``_complete`` status column, identifier-flagged fields
are marked); the records file becomes a Dataset that points at it.

The example input is a small three-form public-health survey
(``plugins/redcap/input-dictionary.csv`` + ``input-records.csv``).

    python examples/import_redcap.py
"""

import _example as ex

ex.banner("REDCap data dictionary + record export -> EVI RO-Crate",
          have="a REDCap data dictionary CSV (and optionally the records CSV)",
          want="a tabular Schema of the export's columns, attached to the records Dataset")

plugin = ex.plugin("redcap")
dictionary = ex.PLUGINS / "redcap" / "input-dictionary.csv"
records = ex.PLUGINS / "redcap" / "input-records.csv"
print(f"dictionary: {dictionary.name}\nrecords:    {records.name}")

crate = plugin.convert(
    "import", dictionary, records=records,
    name="Seasonal respiratory illness survey",
    author="Example Public Health Group",
    keywords=["redcap", "survey", "public health", "respiratory"],
    date_published="2026-01-20", redcap_version="14.5.10",
    crate_dir=dictionary.parent)

ex.summarize(crate)
ex.show_provenance(crate)

schema = next(n for n in crate["@graph"] if "Schema" in str(n.get("@type")))
print(f"\nschema: {len(schema['properties'])} columns, "
      f"{len(schema['required'])} required, "
      f"identifier-flagged: {', '.join(schema.get('identifierFields', [])) or 'none'}")
for name, prop in list(schema["properties"].items())[:8]:
    extra = prop.get("enum") or prop.get("pattern") or ""
    print(f"  {name:<22} {prop['type']:<8} {prop['description'][:40]:<40} {extra}")

ex.write(crate, ex.OUT / "redcap" / "ro-crate-metadata.json")
ex.check_golden(crate, "redcap")
