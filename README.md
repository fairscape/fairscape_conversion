# fairscape-conversion

Your metadata is already written down — as a datasheet, a datapackage, or a
workflow engine's run output. Convert it into a FAIRSCAPE/EVI RO-Crate
(`ro-crate-metadata.json`) instead of re-entering it. One command per format.

```bash
pip install -e .        # from this directory; installs fairscape-conversion
```

The `fairscape import` / `fairscape export` commands come with the
[fairscape CLI](../cli). Without it, every conversion also runs as
`python -m fairscape_conversion.core.cli convert <format> <import|export> IN [OUT]`.

## Import — get an RO-Crate

Pick the row that matches what you have.

| You have | You need | Run |
|---|---|---|
| A Datasheet for Datasets (D4D) | the datasheet as YAML or JSON | `fairscape import d4d datasheet.yaml -o ./crate` |
| A CFDE C2M2 datapackage | the directory of TSVs + `C2M2_datapackage.json` | `fairscape import c2m2 ./datapackage-dir -o ./crate` |
| A Workflow Run RO-Crate | its `ro-crate-metadata.json` | `fairscape import wrroc ro-crate-metadata.json -o ./crate` |
| A finished Cromwell/WDL run | the file from `cromwell run -m metadata.json` | `fairscape import cromwell metadata.json -o ./crate` |
| A finished Snakemake run | the records JSON from `snakemake --reporter fairscape` | `fairscape import snakemake records.json -o ./crate` |
| Finished MLflow runs | the tracking store (an `mlruns` dir or tracking URI) and `pip install mlflow` | `fairscape import mlflow ./mlruns --experiment NAME -o ./crate` |
| A CPM RO-Crate (distributed provenance bundles) | the crate directory: `ro-crate-metadata.json` + its `CPMProvenanceFile` PROV-N/PROV-JSON files | `fairscape import cpm ./crate-dir -o ./evi-crate` |

## Export — from an RO-Crate

| You want | Run |
|---|---|
| A D4D datasheet | `fairscape export d4d ro-crate-metadata.json` |
| A Workflow Run RO-Crate | `fairscape export wrroc ro-crate-metadata.json` |
| An MLCommons Croissant document | `fairscape export croissant ro-crate-metadata.json` |
| A CPM provenance document (PROV-JSON, or PROV-N with `--provn`) | `fairscape export cpm ro-crate-metadata.json` |

## Try it — no data needed

Every conversion above has a runnable example in [`examples/`](examples),
on real input that ships with the package. They need nothing installed:

```bash
python examples/run_all.py            # all nine, with a pass/fail table
python examples/import_d4d.py         # or just the one you care about
```

Each prints what went in, what came out, the provenance edges it created, and
whether the result still matches the plugin's reviewed golden file.

**[`examples/mlflow/mlflow_to_rocrate.ipynb`](examples/mlflow/mlflow_to_rocrate.ipynb)**
is the end-to-end walk-through: it trains a scikit-learn model with MLflow
tracking, converts the store it just created, validates the crate, and renders
its datasheet and provenance graph inline. A three-step pipeline with
`usedMLModel` lives next to it in [`examples/mlflow/pipeline/`](examples/mlflow/pipeline).
Both are checked in with their outputs.

The inputs and expected outputs the examples run on live inside each plugin:

| format | example input | expected output |
|---|---|---|
| d4d | `plugins/d4d/input.yaml` (the AI-READI datasheet) | `plugins/d4d/golden.json` |
| c2m2 | `plugins/c2m2/input-datapackage/` (miniature datapackage) | `plugins/c2m2/golden.json` |
| wrroc | `plugins/wrroc/input.json` (CWL revsort run crate) | `plugins/wrroc/golden.json` |
| cromwell | `plugins/cromwell/input.json` (scatter workflow records) | `plugins/cromwell/golden.json` |
| snakemake | `plugins/snakemake/input.json` (3-rule chain records) | `plugins/snakemake/golden.json` |
| mlflow | `plugins/mlflow/input.json` (iris experiment records) | `plugins/mlflow/golden.json` |
| croissant | `plugins/croissant/input.json` (export this crate) | `plugins/croissant/golden.json` |
| cpm | `plugins/cpm/input-crate/` (the CPM reference crate's provenance files, [zenodo 7676924](https://zenodo.org/records/7676924)) | `plugins/cpm/golden.json` (+ `golden-export.json`) |

## From Python

```python
import yaml
from fairscape_conversion.plugins import d4d

crate = d4d.convert("import", yaml.safe_load(open("datasheet.yaml")))
```

Same shape for every format: `wrroc`, `c2m2`, `cromwell`, `snakemake`,
`mlflow`, `cpm` (`convert("import", ...)`), and `d4d`/`wrroc`/`croissant`/`cpm`
(`convert("export", crate)`). `cpm` takes the crate *directory* rather than a
parsed document, because it reads the PROV bundle files registered in the
metadata alongside it.

## More

- Your format isn't listed → [`docs/NEW-PLUGIN.md`](docs/NEW-PLUGIN.md) —
  a converter is a folder of two CSVs plus a small plugin class.
- How the engine works, what's tested → [`docs/INTERNALS.md`](docs/INTERNALS.md)
  and [`MAPPING-SCHEMA.md`](MAPPING-SCHEMA.md).
