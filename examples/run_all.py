#!/usr/bin/env python3
"""Run every example in this folder and report which ones worked.

    python examples/run_all.py              # the twelve scripted examples
    python examples/run_all.py --notebook   # also execute the MLflow notebook

Each script runs in its own process (one of them chdirs, and a couple write
files), so a failure is isolated to its own row. Output lands in
``examples/out/``, which is gitignored.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

EXAMPLES = [
    ("import_d4d.py", "D4D datasheet -> crate"),
    ("import_c2m2.py", "C2M2 datapackage -> crate"),
    ("import_wrroc.py", "Workflow Run RO-Crate -> crate"),
    ("import_cromwell.py", "Cromwell run -> crate"),
    ("import_snakemake.py", "Snakemake run -> crate"),
    ("import_mlflow.py", "MLflow experiment -> crate"),
    ("export_d4d.py", "crate -> D4D datasheet"),
    ("export_wrroc.py", "crate -> Workflow Run RO-Crate"),
    ("export_croissant.py", "crate -> MLCommons Croissant"),
    ("import_snakemake_variants.py", "real Snakemake run -> crate"),
    ("import_cromwell_variants.py", "real Cromwell run -> crate"),
    ("export_croissant_variants.py", "real run's crate -> Croissant"),
]

NOTEBOOK = HERE / "mlflow" / "mlflow_to_rocrate.ipynb"


def run(script, quiet):
    result = subprocess.run([sys.executable, str(HERE / script)],
                            cwd=HERE, capture_output=True, text=True)
    if result.returncode != 0 and not quiet:
        print(result.stdout[-2000:])
        print(result.stderr[-2000:], file=sys.stderr)
    # The examples that can check themselves say so on stdout.
    verdict = "DIFFERS FROM" not in result.stdout
    return result.returncode == 0 and verdict


def run_notebook(quiet):
    print(f"\nexecuting {NOTEBOOK.relative_to(HERE.parent)} "
          "(trains a model, then converts — takes ~30s)")
    result = subprocess.run(
        [sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook",
         "--execute", "--inplace", "--ExecutePreprocessor.timeout=900",
         NOTEBOOK.name],
        cwd=NOTEBOOK.parent, capture_output=True, text=True)
    if result.returncode != 0 and not quiet:
        print(result.stderr[-3000:], file=sys.stderr)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", action="store_true",
                        help="also execute examples/mlflow/mlflow_to_rocrate.ipynb "
                             "(needs mlflow, scikit-learn, pandas and jupyter; "
                             "rewrites examples/mlflow/crate/)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="do not echo a failing example's output")
    args = parser.parse_args()

    results = []
    for script, description in EXAMPLES:
        print(f"running {script} ...", end=" ", flush=True)
        ok = run(script, args.quiet)
        print("ok" if ok else "FAILED")
        results.append((script, description, ok))

    if args.notebook:
        results.append(("mlflow/mlflow_to_rocrate.ipynb",
                        "MLflow (live) -> crate", run_notebook(args.quiet)))

    print(f"\n{'example':<34} {'what it shows':<34} result")
    print(f"{'-' * 34} {'-' * 34} ------")
    for script, description, ok in results:
        print(f"{script:<34} {description:<34} {'ok' if ok else 'FAILED'}")

    failed = [script for script, _, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} examples ran clean")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
