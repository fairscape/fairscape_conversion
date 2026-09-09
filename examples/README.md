# Examples

One runnable example per conversion, each on real input that ships with the
package. Every script prints what went in, what came out, and — where the
conversion is deterministic — whether it matches the plugin's reviewed
`golden.json`. Nothing needs installing first: the scripts bind
`fairscape_conversion` to this checkout.

```bash
python examples/run_all.py            # all nine, with a pass/fail table
python examples/import_mlflow.py      # or just the one you care about
```

Output goes to `examples/out/` (gitignored). The one exception is the MLflow
notebook, whose crate is checked in.

## Import — you have something, you want a crate

| You have | Example | Input it uses |
|---|---|---|
| A Datasheet for Datasets | [`import_d4d.py`](import_d4d.py) | the AI-READI datasheet |
| A CFDE C2M2 datapackage | [`import_c2m2.py`](import_c2m2.py) | a miniature datapackage of TSVs |
| A Workflow Run RO-Crate | [`import_wrroc.py`](import_wrroc.py) | a CWL revsort run |
| A finished Cromwell/WDL run | [`import_cromwell.py`](import_cromwell.py) | a scatter workflow's metadata |
| A finished Snakemake run | [`import_snakemake.py`](import_snakemake.py) | a three-rule chain |
| MLflow runs | [`import_mlflow.py`](import_mlflow.py) | an iris experiment's records |

## Export — you have a crate, you want something else

| You want | Example | What it shows |
|---|---|---|
| A D4D datasheet | [`export_d4d.py`](export_d4d.py) | the round trip, and what it does and doesn't preserve |
| A Workflow Run RO-Crate | [`export_wrroc.py`](export_wrroc.py) | EVI Computations back as schema.org CreateActions |
| An MLCommons Croissant document | [`export_croissant.py`](export_croissant.py) | EVI Schemas becoming Croissant recordSets |

`export_croissant.py` deliberately takes the crate `import_c2m2.py` produces,
so the two chain: **datapackage → crate → Croissant**. That is the point of
having one hub format in the middle — every importer feeds every exporter.

## The full walk-through

**[`mlflow/mlflow_to_rocrate.ipynb`](mlflow/mlflow_to_rocrate.ipynb)** is the
end-to-end one: it trains a scikit-learn model with MLflow tracking, converts
the store it just created, validates the crate, and renders its datasheet and
provenance graph inline. It ends with [`mlflow/pipeline/`](mlflow/pipeline), a
three-step prepare → train → evaluate pipeline whose evaluate run `usedMLModel`
the trained model. Both notebook and crates are checked in with their outputs.
See [`mlflow/README.md`](mlflow/README.md).

Everything else on this page runs on fixtures and finishes instantly; that
notebook is the one that starts from nothing and needs `mlflow`,
`scikit-learn` and `pandas` installed.

## Reading them

Each script is short and its docstring is the explanation — start with the
docstring, then the ~15 lines under it. Shared plumbing (path setup, the
node/edge printers, the golden check) lives in [`_example.py`](_example.py) so
the scripts stay about their format.

Every conversion is also available as a one-liner, in Python:

```python
from fairscape_conversion.plugins import d4d
crate = d4d.convert("import", yaml.safe_load(open("datasheet.yaml")))
```

or on the command line:

```bash
python -m fairscape_conversion.core.cli convert d4d import datasheet.yaml crate.json
```

## Which mapping made that node?

Every property in every output above is one row in a CSV: `plugins/<format>/
entities.csv` says what each source thing becomes, `properties.csv` says which
field lands where. If an example's output surprises you, those two files are
where the answer is — see [`../MAPPING-SCHEMA.md`](../MAPPING-SCHEMA.md).
