#!/usr/bin/env python3
"""Use case: a pipeline produced a table and you want it loadable from an ML
data ecosystem.

The input is the crate the real Snakemake run produced
(``snakemake-variant-calling/``), whose variant summary TSV carries an EVI
Schema — six columns, inferred from the file. Croissant is what Hugging Face,
Kaggle and TensorFlow Datasets read, so the export turns that crate into a
document ``mlcroissant`` can open and stream rows out of.

Two things an EVI crate has to give up on the way, both shown below:

* Croissant's ``FileObject`` needs a ``contentUrl`` — a file you can fetch.
  A crate happily describes files that no longer exist (Snakemake deleted the
  ``temp()`` alignments as soon as they had been sorted); those Datasets carry
  a ``localPath``, not a ``contentUrl``, and so cannot become FileObjects.
* Croissant wants a checksum on every FileObject. Snakemake does not hash its
  outputs, so nothing in the crate carries one until something computes them —
  which is what this script does before exporting.

    python examples/export_croissant_variants.py
"""

import hashlib
import os
from pathlib import Path

import _example as ex

RUN = Path(__file__).resolve().parent / "snakemake-variant-calling"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


ex.banner("A real run's crate -> MLCommons Croissant",
          have="the EVI crate of the Snakemake variant-calling run",
          want="a croissant.json an ML data loader can consume")

os.chdir(RUN)                       # contentUrls are relative to the crate
crate = ex.read("ro-crate-metadata.json")

datasets = [n for n in crate["@graph"] if "EVI#Dataset" in str(n.get("@type"))]
schemas = [n for n in crate["@graph"] if "Schema" in str(n.get("@type"))]
gone = [n for n in datasets if not n.get("contentUrl")]
print(f"{len(crate['@graph'])} crate nodes in: {len(datasets)} Dataset(s), "
      f"{len(schemas)} Schema(s)")
print(f"  {len(gone)} Dataset(s) describe files that are gone "
      f"({', '.join(str(n.get('name')) for n in gone)}) — dropped, "
      "a FileObject without a contentUrl is not valid Croissant")

hashed = 0
keep = []
for node in crate["@graph"]:
    if node in gone:
        continue
    url = node.get("contentUrl")
    if ("EVI#Dataset" in str(node.get("@type")) and url
            and not url.startswith(("http://", "https://"))
            and Path(url).is_file()):
        node["sha256"] = sha256(url)
        hashed += 1
    keep.append(node)
crate["@graph"] = keep
print(f"  sha256 computed for {hashed} file(s)")

croissant = ex.plugin("croissant").convert("export", crate)

print(f"\ncroissant '{croissant.get('name')}'")
print(f"  conformsTo {croissant.get('dct:conformsTo')}")
print(f"  {len(croissant.get('distribution', []))} distribution entr(ies), "
      f"{len(croissant.get('recordSet', []))} recordSet(s)")
for record_set in croissant.get("recordSet", []):
    fields = record_set.get("field", [])
    print(f"  recordSet {str(record_set.get('name'))[:34]:<36} "
          f"{len(fields)} field(s): "
          + ", ".join(f"{f['name']} ({f['dataType'].split(':')[-1]})"
                      for f in fields))

# Written into the crate folder on purpose: a Croissant document resolves its
# relative contentUrls from its own directory, so this is the copy a loader
# can actually read the data through.
ex.write(croissant, RUN / "croissant.json")

# The proof: MLCommons' own library validates the document and streams the
# real rows back out of results/calls/variant_summary.tsv.
try:
    import mlcroissant as mlc
except ImportError:
    print("\ninstall mlcroissant to have MLCommons' own loader check this file")
else:
    dataset = mlc.Dataset(jsonld="croissant.json")
    print(f"\nmlcroissant loaded '{dataset.metadata.name}'")
    print(f"  errors: {dataset.metadata.issues.errors or 'none'}")
    record_set = dataset.metadata.record_sets[0]
    rows = list(dataset.records(record_set=record_set.uuid))
    print(f"  {len(rows)} record(s) read back from the TSV; first three:")
    for row in rows[:3]:
        print("    " + ", ".join(
            f"{k.split('/')[-1]}={v.decode() if isinstance(v, bytes) else v}"
            for k, v in row.items()))
