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

## Export — from an RO-Crate

| You want | Run |
|---|---|
| A D4D datasheet | `fairscape export d4d ro-crate-metadata.json` |
| A Workflow Run RO-Crate | `fairscape export wrroc ro-crate-metadata.json` |
| An MLCommons Croissant document | `fairscape export croissant ro-crate-metadata.json` |

## Try it — no data needed

Every format ships a real example input and its expected output inside its
plugin folder, so you can run any conversion right now:

```bash
fairscape import d4d plugins/d4d/input.yaml -o /tmp/crate
```

| format | example input | expected output |
|---|---|---|
| d4d | `plugins/d4d/input.yaml` (the AI-READI datasheet) | `plugins/d4d/golden.json` |
| c2m2 | `plugins/c2m2/input-datapackage/` (miniature datapackage) | `plugins/c2m2/golden.json` |
| wrroc | `plugins/wrroc/input.json` (CWL revsort run crate) | `plugins/wrroc/golden.json` |
| cromwell | `plugins/cromwell/input.json` (scatter workflow records) | `plugins/cromwell/golden.json` |
| snakemake | `plugins/snakemake/input.json` (3-rule chain records) | `plugins/snakemake/golden.json` |
| mlflow | `plugins/mlflow/input.json` (iris experiment records) | `plugins/mlflow/golden.json` |
| croissant | `plugins/croissant/input.json` (export this crate) | `plugins/croissant/golden.json` |

## From Python

```python
import yaml
from fairscape_conversion.plugins import d4d

crate = d4d.convert("import", yaml.safe_load(open("datasheet.yaml")))
```

Same shape for every format: `wrroc`, `c2m2`, `cromwell`, `snakemake`,
`mlflow` (`convert("import", ...)`), and `d4d`/`wrroc`/`croissant`
(`convert("export", crate)`).

## More

- Your format isn't listed → [`docs/NEW-PLUGIN.md`](docs/NEW-PLUGIN.md) —
  a converter is a folder of two CSVs plus a small plugin class.
- How the engine works, what's tested → [`docs/INTERNALS.md`](docs/INTERNALS.md)
  and [`MAPPING-SCHEMA.md`](MAPPING-SCHEMA.md).
