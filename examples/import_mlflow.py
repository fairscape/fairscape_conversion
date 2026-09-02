#!/usr/bin/env python3
"""Use case: you tracked training in MLflow and need the run described.

MLflow already holds the params, metrics, dataset inputs, artifacts and models
for every run. It has no end-of-run hook, so this is a post-hoc exporter: it
walks a finished experiment through the ``MlflowClient`` read API and maps it
onto EVI — runs become ``Computation``s (nested runs ``isPartOf`` their
parent), logged models and artifacts become ``Dataset``s, and a logged
dataset's column spec becomes an EVI ``Schema`` without reading a byte of the
data.

This script runs on a pre-extracted records dict (``plugins/mlflow/input.json``)
so it needs no MLflow install. **For the live path — train a model, convert its
tracking store, inspect the crate — open the notebook next door:**

    examples/mlflow/mlflow_to_rocrate.ipynb

which is the same conversion against a store it creates as it goes.

    python examples/import_mlflow.py
"""

import _example as ex

ex.banner("MLflow experiment -> EVI RO-Crate",
          have="a tracking store (mlruns dir, sqlite, or a tracking server)",
          want="the runs, models and datasets as a citable crate")

records = ex.read(ex.PLUGINS / "mlflow" / "input.json")
print(f"experiment {records['experiment']['name']!r} — "
      f"{len(records['runs'])} run(s), {len(records['datasets'])} logged "
      f"dataset(s), {len(records['models'])} model(s), "
      f"{len(records['files'])} artifact(s)")

# A tracking URI would work here too — convert("import", "./mlruns",
# experiment="iris-classifier", crate_dir="./crate") extracts first. Passing
# records keeps this example hermetic.
crate = ex.plugin("mlflow").convert("import", records)

ex.summarize(crate)
ex.show_provenance(crate)

# Re-running the extraction of an unchanged store must mint the same ARKs;
# that is what makes a crate re-exportable without churning identifiers.
again = ex.plugin("mlflow").convert("import", ex.read(ex.PLUGINS / "mlflow" / "input.json"))
same = [n["@id"] for n in crate["@graph"]] == [n["@id"] for n in again["@graph"]]
print(f"\nARKs stable across a second conversion: {same}")

ex.write(crate, ex.OUT / "mlflow" / "ro-crate-metadata.json")
ex.check_golden(crate, "mlflow")
