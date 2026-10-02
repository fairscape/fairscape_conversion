# fairscape-conversion

[![PyPI](https://img.shields.io/pypi/v/fairscape-conversion)](https://pypi.org/project/fairscape-conversion/)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/pypi/l/fairscape-conversion)](https://github.com/fairscape/fairscape_conversion)

fairscape-conversion builds a [FAIRSCAPE](https://fairscape.github.io) evidence
RO-Crate from metadata that already describes a dataset or a computation. A
Datasheet for Datasets, a Frictionless or C2M2 data package, a REDCap data
dictionary, or the record written by Cromwell, Snakemake, Galaxy, or MLflow
becomes `ro-crate-metadata.json`: the datasets, the software, and the
computations, linked with the identifiers FAIRSCAPE uses for its evidence
graph.

That crate can be written out again as MLCommons Croissant, a Datasheet for
Datasets, a Workflow Run RO-Crate, a Frictionless Data Package, or a PROV
document. This package is the **create** step of FAIRSCAPE, next to
[fairscape_models](https://github.com/fairscape/fairscape_models).
Python 3.10 or newer. Apache-2.0.

## Install

**Recommended:** install the published package from PyPI, with
[uv](https://docs.astral.sh/uv/). That is enough to convert your own files.
The quick start below is the first thing to run.

A clone is a separate path. Use it to run the examples and tests in this
repository, or to use `track` and schema inference from this tree (version
0.2.2) while the [PyPI](https://pypi.org/project/fairscape-conversion/)
release is behind it.

### uv (recommended)

```bash
uv venv
uv pip install fairscape-conversion
uv run python -c "import fairscape_conversion; print('fairscape-conversion is installed')"
```

`uv` creates `.venv` and installs into it. `uv run` uses that environment.
In the quick start, put `uv run` in front of the convert line.

For a single run that keeps no environment on disk, put
`uv run --with fairscape-conversion` in front of that same line.

### pip

pip installs the same PyPI release into a virtual environment you activate:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -U pip
python -m pip install fairscape-conversion
```

Later pip examples assume this environment is active. `.venv/bin/python`
(Windows: `.venv\Scripts\python`) is the same interpreter.

A live MLflow tracking store needs the MLflow client as well. On the uv
environment, `uv pip install mlflow`. On the pip environment,
`python -m pip install mlflow`.

### Clone this repository

Clone to run `examples/` or `pytest`, or to install `track` and the `schemas`
extra from this tree. `examples/` ships in the git repository. An editable
install (`-e`) points the environment at the clone, so the examples and tests
run this tree.

```bash
git clone https://github.com/fairscape/fairscape_conversion.git
cd fairscape_conversion
```

uv:

```bash
uv venv
uv pip install -e ".[schemas]"
uv pip install pytest
uv run python examples/run_all.py
uv run python -m pytest
```

pip:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e ".[schemas]"
python -m pip install pytest
python examples/run_all.py
python -m pytest
```

| Add this on the clone | uv | pip |
|---|---|---|
| Schema inference for Cromwell and MLflow outputs | `uv pip install -e ".[schemas]"` | `python -m pip install -e ".[schemas]"` |
| A live MLflow tracking store | `uv pip install mlflow` | `python -m pip install mlflow` |
| The test suite | `uv pip install pytest` | `python -m pip install pytest` |
| The MLflow notebook | `uv pip install mlflow scikit-learn pandas jupyter` | `python -m pip install mlflow scikit-learn pandas jupyter` |

The `schemas` extra adds the readers for tabular and scientific files (CSV,
Parquet, HDF5, and others). MLflow is its own package.

## Quick start

After the PyPI install above, this writes a small datasheet and converts it.

```bash
cat > datasheet.yaml << 'EOF'
name: example-dataset
title: Example dataset
description: A small datasheet, to try the converter.
license: CC0-1.0
EOF

mkdir -p my-crate
python -m fairscape_conversion.core.cli convert d4d import datasheet.yaml my-crate/ro-crate-metadata.json
```

That prints `wrote my-crate/ro-crate-metadata.json`. With uv and no activated
environment, prefix the convert line with `uv run`.

The same call from Python:

```python
import yaml
from fairscape_conversion.plugins import d4d

with open("datasheet.yaml") as handle:
    crate = d4d.convert("import", yaml.safe_load(handle))
```

A full Datasheet for Datasets ships inside the package:

```python
from importlib.resources import files
import yaml
from fairscape_conversion.plugins import d4d

text = files("fairscape_conversion.plugins.d4d").joinpath("input.yaml").read_text()
crate = d4d.convert("import", yaml.safe_load(text))
```

In this repository that file is [`plugins/d4d/input.yaml`](plugins/d4d/input.yaml).

## Command

Every format uses the same command:

```bash
python -m fairscape_conversion.core.cli convert <format> <import|export> INPUT [OUTPUT]
```

`INPUT` is read as YAML when its name ends in `.yaml` or `.yml`, and as JSON
otherwise. `OUTPUT` is written the same way. Leave `OUTPUT` off to print the
result.

Flags the command accepts:

| Flag | What it does |
|---|---|
| `--link-crate DIR` | Reuse identifiers from an upstream crate. Repeat for more than one. |
| `--crate-dir DIR` | Where this crate's relative paths resolve. |
| `--records FILE` | REDCap record export, beside the data dictionary. |
| `--provn` | CPM export writes PROV-N. The default export is PROV-JSON. |

A word after the input path is the output file. `experiment` is not a flag;
it is a keyword of `mlflow.convert`, shown below.

Two more commands:

```bash
python -m fairscape_conversion.core.cli track SCRIPT [--crate-dir DIR] [-- SCRIPT_ARGS]
python -m fairscape_conversion.core.cli link <crate-dir-or-metadata.json> --link-crate DIR [-o OUT]
```

In Python, import the format module and call `convert` with `"import"` or
`"export"`. The quick start does this for a datasheet: it loads the YAML and
passes that dictionary to `d4d.convert`. The table below says what each format
is given. Cromwell and MLflow take the path of the metadata file or the
tracking store; those calls are in their own sections.

## Formats

| Format | Import | Export | What you pass |
|---|---|---|---|
| `d4d` | yes | yes | A Datasheet for Datasets, YAML or JSON. Export writes that datasheet back out. |
| `snakemake` | yes | | Records JSON from `snakemake --reporter fairscape`. |
| `wrroc` | yes | yes | A Workflow Run RO-Crate `ro-crate-metadata.json` (CWL, Galaxy, and others). |
| `galaxy` | yes | | An invocation export (`.tar.gz`, `.zip`, or a folder) or a `.ga` file. |
| `redcap` | yes | | The data dictionary CSV. Add `--records DATA.csv` to include the record export. |
| `frictionless` | yes | yes | A `datapackage.json` or the folder that contains it. |
| `c2m2` | yes | | A CFDE C2M2 datapackage folder. |
| `cpm` | yes | yes | A CPM RO-Crate folder (metadata plus its PROV bundle files). |
| `croissant` | | yes | An RO-Crate, written as MLCommons Croissant. |
| `cromwell` | yes | | A Cromwell `metadata.json`. Call it from Python, below. |
| `mlflow` | yes | | An `mlruns` directory or a tracking URI. Call it from Python, below. |
| `python` | yes | | A run record written by `track`. |

```bash
python -m fairscape_conversion.core.cli convert snakemake import records.json crate.json
python -m fairscape_conversion.core.cli convert galaxy import invocation.tar.gz crate.json
python -m fairscape_conversion.core.cli convert redcap import dictionary.csv crate.json --records DATA.csv
python -m fairscape_conversion.core.cli convert frictionless import ./package crate.json
python -m fairscape_conversion.core.cli convert croissant export ro-crate-metadata.json croissant.json
python -m fairscape_conversion.core.cli convert cpm export ro-crate-metadata.json prov.json
python -m fairscape_conversion.core.cli convert cpm export ro-crate-metadata.json prov.provn --provn
```

C2M2 writes a crate directory next to the datapackage, named `<slug>-crate`,
with the source tables copied in, and prints the crate. To choose the folder:

```python
from fairscape_conversion.plugins import c2m2
c2m2.convert("import", "./datapackage-dir", output_path="./crate")
```

CPM import wants the crate directory, because the PROV bundle files sit beside
`ro-crate-metadata.json`:

```bash
python -m fairscape_conversion.core.cli convert cpm import ./crate-dir evi.json
```

### Cromwell

`cromwell run -m metadata.json` writes a metadata file. Pass that path to
Python. The importer opens the file itself, reads each call, and can copy the
submitted workflow into the crate directory.

```python
from fairscape_conversion.plugins import cromwell

cromwell.convert("import", "metadata.json", crate_dir="my-crate", schemas=True)
```

`schemas=True` adds an EVI Schema for each supported data file. Install the
`schemas` extra first. Leave it off and the computations and files are still
converted.

On the command line, a `.json` input is parsed into a document before the
plugin sees it. Cromwell metadata is not that document, so the path has to
reach `cromwell.convert` as a string.

### MLflow

Install `mlflow`, then pass the tracking store and the experiment. The store
is an `mlruns` directory or any MLflow tracking URI. `experiment` is the
experiment name or id. `run_id` exports one run and its nested children.

```python
from fairscape_conversion.plugins import mlflow

mlflow.convert(
    "import",
    "./mlruns",
    experiment="NAME",
    crate_dir="my-crate",
    schemas=True,
)
```

`schemas=True` infers an EVI Schema for each copied data artifact. Column
schemas for logged dataset inputs are written either way. Artifacts are copied
into `crate_dir` so the crate stands on its own; pass `copy_artifacts=False`
to point at the store instead.

The same path rule as Cromwell applies: the store has to arrive as a string.
[`examples/mlflow/mlflow_to_rocrate.ipynb`](examples/mlflow/mlflow_to_rocrate.ipynb)
trains a model, converts the store it just wrote, and renders the crate.

## Track a Python run

`track` runs a script, records the files it reads and writes, and adds the run
to a crate directory. The crate is created on first use. Each later run is
appended. An input the crate already describes — usually an earlier run's
output — reuses that node, so the provenance chain runs through the crate.

`track` is in this repository (0.2.2). Install from a clone, above, to use it.

```bash
python -m fairscape_conversion.core.cli track clean.py --crate-dir my-crate -- data/raw.csv data/clean.csv
python -m fairscape_conversion.core.cli track plot.py  --crate-dir my-crate -- data/clean.csv data/plot.png
```

Everything after `--` is passed to the script. The capture covers `open`,
`pathlib`, and, when those libraries are installed, pandas, numpy, and
matplotlib. `--input FILE` records a file the capture misses. `--link-crate DIR`
reuses entities from an upstream crate. `--name`, `--author`, and repeatable
`--keyword` set the run's labels. `--start-clean` drops previous runs from
the crate before this one is added.

The script is copied to `software/<name>-<hash>.py` inside the crate directory
when it does not already live there.

In Jupyter, after the clone install above:

```python
%load_ext fairscape_conversion.plugins.python
```

```python
%%fairscape track --crate-dir my-crate --name normalize
df = pd.read_csv("raw.csv")
df.to_csv("normalized.csv")
```

A cell that reads or writes nothing is left out of the crate.

## Link two crates

When this run's inputs were another run's outputs, name the upstream crate.
Matching files keep the upstream identifiers, and the evidence graph can
continue from one crate into the other.

```bash
python -m fairscape_conversion.core.cli convert snakemake import records.json crate.json \
    --link-crate /path/to/upstream-crate

python -m fairscape_conversion.core.cli link ./crate-dir --link-crate /path/to/upstream-crate
```

`--link-crate` can be repeated. `--crate-dir DIR` sets where this crate's
relative paths resolve. With a convert command and no `--crate-dir`, they
resolve from the output file's folder.

```python
from fairscape_conversion.plugins import mlflow

crate = mlflow.convert(
    "import",
    "./mlruns",
    experiment="NAME",
    linked_crates=["/path/to/upstream-crate"],
)
```

Worked pairs, including what is left unlinked on purpose, are in
[`examples/linked-crates/`](examples/linked-crates).

## Examples

From a clone, after the install in [Clone this repository](#clone-this-repository):

```bash
python examples/run_all.py             # each example, then a pass/fail table
python examples/import_d4d.py          # or one script
python examples/run_all.py --notebook  # also executes the MLflow notebook
```

With uv and no activated environment, prefix those with `uv run`.

Each script prints what it converted. The fixture scripts check the result
against that plugin's reviewed `golden.json`. Output goes to `examples/out/`.
The linked MLflow example needs `mlflow` and `pandas`. The scripts bind the
clone, so they run the code you have checked out.

The notebook needs `mlflow`, `scikit-learn`, `pandas`, and `jupyter`. It
rewrites the crate checked in under `examples/mlflow/`. The catalog of every
script, including public Cromwell and Galaxy runs, is
[`examples/README.md`](examples/README.md).

## Tests

From a clone, with pytest installed as in the clone section:

```bash
# uv
uv pip install pytest
uv run python -m pytest

# pip, environment already active
python -m pip install pytest
python -m pytest
```

Parity tests compare a few converters with the original implementations and
skip when those trees are not checked out beside this one. The other tests run
anywhere the dependencies import.

## Add a format

A converter is a folder of two CSV mapping files and a small plugin class.
Copy [`plugins/example/`](plugins/example/) and follow
[`docs/NEW-PLUGIN.md`](docs/NEW-PLUGIN.md). The column reference is
[`MAPPING-SCHEMA.md`](MAPPING-SCHEMA.md). How a conversion runs is
[`docs/INTERNALS.md`](docs/INTERNALS.md).

## License

Apache-2.0.
