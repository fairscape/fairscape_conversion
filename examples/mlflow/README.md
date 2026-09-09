# MLflow → RO-Crate

[`mlflow_to_rocrate.ipynb`](mlflow_to_rocrate.ipynb) does four things:

1. **Train** a scikit-learn model with ordinary MLflow tracking
2. **Convert** the tracking store into a FAIRSCAPE RO-Crate with one call
3. **Look** at the result: the datasheet and the provenance graph render inside the notebook
4. **Scale up** to [`pipeline/`](pipeline): prepare → train (a grid of nested runs) → evaluate,
   where the evaluate run `usedMLModel` the trained model and every step's inputs trace back
   to the step before. Its datasheet and graph render at the end of the notebook.

The notebook is checked in **with its outputs**, so you can read it without running
anything. [`crate/`](crate) is what that run produced, datasheet and graph included.

## Run it yourself

```bash
pip install mlflow scikit-learn pandas fairscape-cli
pip install -e ../..                          # fairscape-conversion
cd examples/mlflow && jupyter lab mlflow_to_rocrate.ipynb
```

Running it rewrites `mlflow.db`, `mlruns/`, `work/`, `crate/` and `pipeline/crate/`
next to the notebook. Scratch files are gitignored; `git checkout examples/mlflow`
restores the committed crates.

## What is in the crate

```
crate/
  ro-crate-metadata.json              the RO-Crate, 13 nodes
  ro-crate-datasheet.html             human-readable datasheet (fairscape-cli build datasheet)
  provenance-graph.html               interactive provenance graph of the model (fairscape-cli build evidence-graph)
  rf-baseline-<run>/
    confusion_matrix.csv              a logged artifact
    model/                            the sklearn model, copied whole
  feature-importance-<run>/
    feature_importance.csv            the nested run's artifact
```

| in the crate | came from |
|---|---|
| `EVI#ROCrate` root | the experiment, plus the settings passed to `convert` |
| 2 × `EVI#Computation` | the two MLflow runs; the nested one `isPartOf` its parent |
| 2 × `EVI#Software` | `mlflow.source.name` (the training script) and MLflow itself |
| `EVI#Dataset` "iris" | `mlflow.log_input(...)`, with `digest` and row count |
| `EVI#MLModel` "model" | `log_model`, keeping its sklearn flavor and `trainedOn` the run's dataset |
| 2 × `EVI#Dataset` (`.csv`) | `log_artifact`, each `generatedBy` its run |
| 3 × `EVI#Schema` | one from the logged dataset's column spec, two inferred from the copied CSVs |

Each `Computation` carries the command, `runBy`, start/end times, `parameter`
(from `log_params`), `additionalProperty` (from `log_metrics`) and `mlflowRunId`.

## Without a notebook

```python
from fairscape_conversion.plugins import mlflow

crate = mlflow.convert("import", "sqlite:///mlflow.db",
                       experiment="iris-classifier", crate_dir="./crate")
```

`"import"` takes any tracking URI: `sqlite:///…`, an `mlruns/` directory, or a
remote `http(s)://` tracking server. Scope it with `experiment=` (all its runs)
or `run_id=` (that run plus its nested children). `../import_mlflow.py` runs the
same conversion on a pre-extracted fixture with no MLflow install needed.
