#!/usr/bin/env python3
"""Use case: an MLflow experiment analysed files a Nextflow pipeline produced,
and you want the MLflow crate to know where its inputs came from.

Two independent runs, two crates, no shared memory between them:

* ``linked-crates/nextflow-run/results/`` — a crate the ``nf-fairscape``
  plugin wrote when the pipeline ran: ``letters.txt -> reversed.txt ->
  first_half.txt + second_half.txt``, every file with its own ARK.
* ``linked-crates/mlflow-analysis/`` — an MLflow run (``analyze.py``) that
  read the two halves, logged them as dataset inputs, and logged a report.

Converted on its own, the MLflow crate mints a fresh, producer-less Dataset
for each half. Converted with ``linked_crates=[<the Nextflow crate>]`` it
reuses the Nextflow ARKs instead: each half becomes a *stub* of the Nextflow
entity — same ``@id``, no ``generatedBy``, ``isPartOf`` the Nextflow crate —
and the Nextflow crate appears once as a pointer (``ro-crate-metadata``).
``fairscape-artifacts`` follows that pointer, so the MLflow crate's evidence
graph runs through the vowel scoring, into SPLIT_HALVES, REVERSE and
MAKE_LIST, and stops at the Nextflow run's own inputs. ``vowels.txt``, which
no crate produced, stays a plain input.

    python examples/import_mlflow_linked.py            # convert the checked-in run
    python examples/import_mlflow_linked.py --rerun    # re-run analyze.py first (needs mlflow, pandas)

Nothing MLflow-specific happens in the linking: it reads the finished crate
and matches by path. ``import_snakemake_linked.py`` does the same to a crate
the Snakemake reporter wrote, with no conversion at all.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import _example as ex

HERE = Path(__file__).resolve().parent
NEXTFLOW = HERE / "linked-crates" / "nextflow-run" / "results"
MLFLOW = HERE / "linked-crates" / "mlflow-analysis"
CRATE = MLFLOW / "crate"
TRACKING = f"sqlite:///{MLFLOW / 'mlflow.db'}"

ex.banner("MLflow run over Nextflow outputs -> one linked crate",
          have="an MLflow tracking store, and the crate nf-fairscape wrote for "
               "the pipeline whose outputs the run analysed",
          want="an MLflow crate whose inputs ARE the Nextflow crate's outputs")

if "--rerun" in sys.argv or not (MLFLOW / "mlflow.db").exists():
    (MLFLOW / "mlflow.db").unlink(missing_ok=True)
    shutil.rmtree(MLFLOW / "mlruns", ignore_errors=True)
    print("running analyze.py (mlflow + pandas) ...")
    subprocess.run([sys.executable, str(MLFLOW / "analyze.py")], check=True, cwd=MLFLOW)

to_rocrate = ex.plugin("mlflow")
shutil.rmtree(CRATE, ignore_errors=True)
CRATE.mkdir()

settings = dict(
    experiment="letters-vowel-score",
    crate_dir=str(CRATE),
    copy_artifacts=True,
    name="Vowel score of the letters-chain halves",
    description="An MLflow run that scored the two halves of the letters-chain "
                "pipeline's output by vowel content, converted to an EVI RO-Crate "
                "that links back to the Nextflow crate for its inputs.",
    author="Ada Lovelace",
    keywords="mlflow, letters-chain, linked crates, provenance",
    date_published="2026-09-18T00:00:00-04:00",
)

# -- without the link: what every importer does on its own ------------------
plain = to_rocrate.convert("import", TRACKING, **settings)
plain_inputs = [n for n in plain["@graph"]
                if "Dataset" in str(n.get("@type")) and not n.get("generatedBy")
                and "ROCrate" not in str(n.get("@type"))]
print("\nconverted alone, the run's inputs are fresh, producer-less Datasets:")
for n in plain_inputs:
    print(f"  {n['@id']:<50} {n.get('name')}")

# -- with the link -------------------------------------------------------------
crate = to_rocrate.convert("import", TRACKING, **settings,
                           linked_crates=[str(NEXTFLOW)], link_report=True)
matches = crate.pop("_linking")
print(f"\nconverted with linked_crates=[nextflow-run/results], "
      f"{len(matches)} input(s) resolved to the Nextflow crate:")
for m in matches:
    print(f"  {m['old_id']}\n    -> {m['new_id']}  [{m['method']}]")

ex.summarize(crate)
ex.show_provenance(crate, limit=20)

nodes = {n["@id"]: n for n in crate["@graph"]}
pointer = next(n for n in crate["@graph"] if n.get("ro-crate-metadata"))
print(f"\nthe pointer to the upstream crate:\n  {pointer['@id']}\n"
      f"  ro-crate-metadata: {pointer['ro-crate-metadata']}")
stub = nodes[matches[0]["new_id"]]
print(f"\none stub, as the MLflow crate carries it:")
print(json.dumps({k: stub[k] for k in ("@id", "name", "description", "localPath", "isPartOf")
                  if k in stub}, indent=2))
assert "generatedBy" not in stub, "a stub carries no provenance of its own"
unlinked = [n for n in crate["@graph"] if n.get("name") == "vowels"]
assert unlinked and not unlinked[0].get("isPartOf"), "vowels.txt came from nowhere"
print("\nvowels.txt, which no crate produced, is still a plain input.")

ex.write(crate, CRATE / "ro-crate-metadata.json")

# -- and the artifacts follow the pointer ---------------------------------------
try:
    from fairscape_artifacts import evidence, cli as artifacts_cli
    from fairscape_artifacts.crate import Crate
except ImportError:
    print("\n(fairscape_artifacts not importable: skipping the evidence graph; "
          "pip install -e ../fairscape_artifacts)")
    sys.exit(0)

loaded = Crate.load(str(CRATE))
graph = evidence.build(loaded)["@graph"]
from_upstream = sorted(n.get("name") or i for i, n in graph.items() if n.get("crate"))
print(f"\nevidence graph of the MLflow crate: {len(graph)} nodes, "
      f"{len(from_upstream)} of them reached through the Nextflow crate:")
print("  " + ", ".join(from_upstream))
assert {"SPLIT_HALVES", "REVERSE", "MAKE_LIST", "letters.txt", "reversed.txt"} <= set(from_upstream)

artifacts_cli.main(["all", str(CRATE), "--no-review", "-q"])
print(f"\nwrote {CRATE.relative_to(HERE.parent)}/ro-crate-evidence-graph.html "
      f"and ro-crate-datasheet.html — open either in a browser")
