#!/usr/bin/env python3
"""Use case: you documented a dataset with a Datasheet for Datasets.

A D4D datasheet answers the Gebru et al. questions in prose — motivation,
composition, collection process, uses, distribution, maintenance. All of that
is already metadata; it just isn't machine-readable. This converts it into an
EVI RO-Crate so the same answers become typed nodes a catalog can index.

The example input is the real AI-READI datasheet (``plugins/d4d/input.yaml``).
D4D is bidirectional — ``export_d4d.py`` turns the crate back into a datasheet.

    python examples/import_d4d.py
"""

import _example as ex

ex.banner("D4D datasheet -> EVI RO-Crate",
          have="a datasheet (YAML or JSON) answering the D4D questions",
          want="an ro-crate-metadata.json a catalog can read")

datasheet = ex.read(ex.PLUGINS / "d4d" / "input.yaml")
print(f"datasheet '{datasheet.get('title', '?')}' — "
      f"{len(datasheet)} top-level sections: {', '.join(sorted(datasheet))}")

crate = ex.plugin("d4d").convert("import", datasheet)

ex.summarize(crate)
ex.show_provenance(crate)

# The D4D sections that carry no schema.org equivalent survive as RAI
# (Responsible AI) properties on the root Dataset — the reason the conversion
# is lossless enough to run backwards.
root = next(n for n in crate["@graph"] if "ROCrate" in str(n.get("@type")))
rai = sorted(k for k in root if k.startswith("rai:"))
print(f"\nRAI properties kept on the root: {', '.join(rai) or '(none)'}")

ex.write(crate, ex.OUT / "d4d" / "ro-crate-metadata.json")

# No golden check here: every node is stamped with the running
# fairscape_models version, so the comparison broke on each models release
# rather than on a real change in this conversion.
