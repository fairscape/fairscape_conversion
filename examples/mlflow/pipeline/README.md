# A three-step MLflow pipeline → RO-Crate

Three scripts, three MLflow runs, one crate. Each step is a separate process so
MLflow records the script as the run's source.

| step | what it does | what the crate gets |
|---|---|---|
| `prepare.py` | splits iris into `train.csv` / `test.csv` | a `Computation` that used the raw `iris` dataset and generated both files |
| `train.py` | fits three random forests as nested runs, keeps the best by out-of-bag accuracy | one parent `Computation` with three children (`isPartOf`), each with its parameters, metrics and a model |
| `evaluate.py` | scores the best model on `test.csv` | a `Computation` with **`usedMLModel`** → the model, `usedDataset` → `test.csv`, and predictions, a confusion matrix and a report as outputs |

`train.csv` and `test.csv` are logged as dataset inputs by the consuming steps
and as artifacts by `prepare.py`. The converter notices they are the same files
and links them, so the provenance graph runs unbroken from `predictions.csv`
back to the raw data.

```bash
pip install mlflow scikit-learn pandas matplotlib fairscape-cli
pip install -e ../../..                      # fairscape-conversion
python run_pipeline.py
```

`run_pipeline.py` runs the steps, converts the experiment, and builds
`crate/ro-crate-datasheet.html` and `crate/provenance-graph.html` (rooted at
`predictions.csv`). Open either in a browser, or see them rendered at the end of
[`../mlflow_to_rocrate.ipynb`](../mlflow_to_rocrate.ipynb).

`mlflow.db`, `mlruns/` and `data/` are scratch and gitignored; `crate/` is committed.
