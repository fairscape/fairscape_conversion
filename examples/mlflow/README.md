# MLflow → RO-Crate, end to end

[`mlflow_to_rocrate.ipynb`](mlflow_to_rocrate.ipynb) is the live example: it
trains a scikit-learn model with MLflow tracking, converts the tracking store
it just created into an EVI RO-Crate, and then reads the crate back — graph,
provenance edges, the run in full, the schema MLflow's column spec supplied,
`fairscape_models` validation, and a determinism check on the ARKs.

The notebook is checked in **with its outputs**, so you can read the whole
thing without running anything. [`crate/`](crate) is what that run produced.

## Run it yourself

```bash
pip install mlflow scikit-learn pandas       # to produce the runs
pip install -e ../..                         # fairscape-conversion (optional: the
                                             # notebook falls back to this checkout)
pip install fairscape-cli                    # optional: schema inference for .csv artifacts
cd examples/mlflow && jupyter lab mlflow_to_rocrate.ipynb
```

Running it rewrites `mlruns/`, `work/` and `crate/` next to the notebook.
Those first two are gitignored; `git checkout examples/mlflow/crate` restores
the committed crate.

## What the committed crate contains

```
crate/
  ro-crate-metadata.json              13 nodes
  rf-baseline-<run>/
    confusion_matrix.csv              a logged artifact
    model/                            the sklearn model, copied whole
  feature-importance-<run>/
    feature_importance.csv            the nested run's artifact
```

| in the crate | came from |
|---|---|
| `EVI#ROCrate` root | the experiment, plus the settings you passed to `convert` |
| 2 × `EVI#Computation` | the two MLflow runs; the nested one `isPartOf` its parent |
| `EVI#Software` × 2 | `mlflow.source.name` (the training script) and MLflow itself |
| `EVI#Dataset` "iris" | `mlflow.log_input(...)` — with `digest` and row count |
| `EVI#Dataset` "model" | `log_model`, typed `mls:Model`, keeping its sklearn flavor |
| `EVI#Dataset` × 2 (`.csv`) | `log_artifact`, each `generatedBy` its run |
| `EVI#Schema` × 3 | one from the logged dataset's column spec, two inferred from the copied CSVs |

The `Computation` nodes carry the command, `runBy`, start/end times,
`parameter` (from `log_params`), `additionalProperty` (from `log_metrics`),
and `mlflowRunId`, so every node still points back at the run it came from.

## Without a notebook

`../import_mlflow.py` runs the same conversion on a pre-extracted records
fixture — no MLflow install needed. And nothing here is notebook-specific:

```python
from fairscape_conversion.plugins import mlflow

crate = mlflow.convert("import", "sqlite:///mlflow.db",
                       experiment="iris-classifier", crate_dir="./crate")
```

`"import"` takes any tracking URI — an `mlruns` directory, `sqlite:///…`, or a
remote `http(s)://` tracking server. Scope it with `experiment=` (all its runs)
or `run_id=` (that run plus its nested children).
