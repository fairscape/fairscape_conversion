"""Run the three steps, then convert the experiment into an RO-Crate with a
datasheet and a provenance graph rooted at the final predictions.

    python run_pipeline.py            # from anywhere
"""
from common import CRATE, EXPERIMENT, HERE, TRACKING

import json
import shutil
import subprocess
import sys

from fairscape_conversion.plugins import mlflow as to_rocrate

def run(*cmd):
    subprocess.run([str(c) for c in cmd], check=True, cwd=HERE)

# 1. the pipeline: one process per step, so MLflow records each script as the run's source
(HERE / "mlflow.db").unlink(missing_ok=True)
for stale in ("mlruns", "data"):
    shutil.rmtree(HERE / stale, ignore_errors=True)
for step in ("prepare.py", "train.py", "evaluate.py"):
    run(sys.executable, step)

# 2. the crate
shutil.rmtree(CRATE, ignore_errors=True)
crate = to_rocrate.convert(
    "import", TRACKING,
    experiment=EXPERIMENT,
    crate_dir=CRATE,
    naan="59853",
    name="Iris pipeline — prepare, train, evaluate",
    description="A three-step MLflow pipeline (data split, random-forest grid, "
                "held-out evaluation) converted to an EVI RO-Crate.",
    author="Example Researcher",
    keywords="mlflow, iris, random forest, pipeline, provenance",
    license="https://spdx.org/licenses/CC-BY-4.0",
    schemas=True,
)
(CRATE / "ro-crate-metadata.json").write_text(json.dumps(crate, indent=2, default=str))
print(f"crate: {len(crate['@graph'])} nodes -> {CRATE.relative_to(HERE)}/ro-crate-metadata.json")

# 3. datasheet + provenance graph, starting from the predictions
predictions = next(n["@id"] for n in crate["@graph"] if n.get("name") == "predictions.csv")
run("fairscape-cli", "build", "datasheet", CRATE, "--skip-subcrate-processing")
run("fairscape-cli", "build", "evidence-graph", CRATE, predictions)
