# fairscape-conversion

Turns metadata you already have (a datasheet, a data package, a workflow
engine's run output) into a FAIRSCAPE RO-Crate, so you don't have to type it
in again. It can also export a crate to other formats.

It is the **create** step of [FAIRSCAPE](https://fairscape.github.io), next to
[fairscape_models](https://github.com/fairscape/fairscape_models).

## Install

```bash
pip install fairscape-conversion
```

## Example

```bash
mkdir my-crate
python -m fairscape_conversion.core.cli convert d4d import datasheet.yaml my-crate/ro-crate-metadata.json
```

From Python:

```python
import yaml
from fairscape_conversion.plugins import d4d

crate = d4d.convert("import", yaml.safe_load(open("datasheet.yaml")))
```

Every format works the same way:
`convert <format> <import|export> INPUT [OUTPUT]`.

## Formats

| Import from | Input |
|---|---|
| `d4d` | Datasheet for Datasets (YAML or JSON) |
| `snakemake` | records JSON from `snakemake --reporter fairscape` |
| `cromwell` | `metadata.json` from `cromwell run -m` |
| `galaxy` | an invocation export (`.tar.gz`, `.zip`, folder) or a `.ga` file |
| `mlflow` | an `mlruns` dir or tracking URI, with `--experiment NAME` (needs `pip install mlflow`) |
| `wrroc` | a Workflow Run RO-Crate `ro-crate-metadata.json` (CWL, Galaxy, …) |
| `redcap` | the data dictionary CSV, plus `--records DATA.csv` if you want the records too |
| `frictionless` | a `datapackage.json` or its folder |
| `c2m2` | a CFDE C2M2 datapackage folder |
| `cpm` | a CPM RO-Crate folder with its PROV bundle files |

| Export to | |
|---|---|
| `croissant` | MLCommons Croissant |
| `d4d` | Datasheet for Datasets |
| `wrroc` | Workflow Run RO-Crate |
| `frictionless` | Frictionless `datapackage.json` |
| `cpm` | PROV-JSON (or PROV-N with `--provn`) |

## Details

- **Try every converter with no data of your own.** `python examples/run_all.py`
  runs each one on the sample input that ships in `plugins/<format>/` and
  checks the result against a reviewed golden file.
  [`examples/mlflow/mlflow_to_rocrate.ipynb`](examples/mlflow/mlflow_to_rocrate.ipynb)
  is a full walk-through.
- **Linking crates.** If this run's inputs were another run's outputs, pass
  `--link-crate /path/to/upstream-crate`. The new crate reuses the upstream
  identifiers, so the evidence graph can follow one crate into the other. See
  [`examples/linked-crates/`](examples/linked-crates).
- **Adding a format.** A converter is a folder with two CSV mapping files and
  a small plugin class. See [`docs/NEW-PLUGIN.md`](docs/NEW-PLUGIN.md),
  [`docs/INTERNALS.md`](docs/INTERNALS.md) and
  [`MAPPING-SCHEMA.md`](MAPPING-SCHEMA.md).
