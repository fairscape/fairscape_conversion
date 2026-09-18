"""A small MLflow experiment over files a Nextflow run produced.

Reads the two halves of the letter list that ``../nextflow-run`` wrote
(``results/first_half.txt`` and ``results/second_half.txt``), logs each one
as an MLflow dataset input with its file path as the source, scores the halves
by vowel content, and logs a report as a run artifact. It also logs one input
that came from nowhere — ``vowels.txt`` beside this script — so the linking
pass has something it must leave alone.

Nothing here knows about RO-Crates. The only thing that matters for
provenance is ``source=<path>``: that is what lets the conversion find the
file in the Nextflow crate.

    python analyze.py          # writes mlflow.db + mlruns/ beside this script
"""
import json
import os
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEXTFLOW_RESULTS = (HERE.parent / "nextflow-run" / "results").resolve()
TRACKING = f"sqlite:///{HERE / 'mlflow.db'}"
EXPERIMENT = "letters-vowel-score"

os.environ["MLFLOW_LOGGING_LEVEL"] = "ERROR"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR"] = "false"
warnings.filterwarnings("ignore", category=UserWarning)

import mlflow                      # noqa: E402
import pandas as pd                # noqa: E402

VOWELS = HERE / "vowels.txt"
VOWELS.write_text("a\ne\ni\no\nu\n")

mlflow.set_tracking_uri(TRACKING)
mlflow.set_experiment(EXPERIMENT)


def letters(path: Path) -> pd.DataFrame:
    return pd.DataFrame({"letter": [l.strip() for l in path.read_text().splitlines() if l.strip()]})


with mlflow.start_run(run_name="vowel-score"):
    vowels = set(VOWELS.read_text().split())
    mlflow.log_input(mlflow.data.from_pandas(letters(VOWELS), name="vowels",
                                             source=str(VOWELS)), context="reference")
    report = {}
    for half in ("first_half.txt", "second_half.txt"):
        path = NEXTFLOW_RESULTS / half
        frame = letters(path)
        mlflow.log_input(mlflow.data.from_pandas(frame, name=half, source=str(path)),
                         context="scoring")
        n_vowels = int(frame.letter.isin(vowels).sum())
        report[half] = {"letters": len(frame), "vowels": n_vowels,
                        "vowel_fraction": n_vowels / len(frame)}
        mlflow.log_metric(f"vowel_fraction_{half.split('_')[0]}", report[half]["vowel_fraction"])
    mlflow.log_param("vowel_set", "".join(sorted(vowels)))
    out = HERE / "letter_report.json"
    out.write_text(json.dumps(report, indent=2))
    mlflow.log_artifact(str(out))
    out.unlink()

print("vowel-score:", json.dumps(report))
