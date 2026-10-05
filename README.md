# fairscape-conversion

[![PyPI](https://img.shields.io/pypi/v/fairscape-conversion)](https://pypi.org/project/fairscape-conversion/)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/pypi/l/fairscape-conversion)](https://github.com/fairscape/fairscape_conversion)

fairscape-conversion converts metadata you already have into a
[FAIRSCAPE](https://fairscape.github.io) RO-Crate
(`ro-crate-metadata.json`), and exports that crate to another format.
The crate holds the datasets, the software, and the computations, linked
with the identifiers FAIRSCAPE uses. Use it when a workflow run, a data
package, a dataset description, or an experiment log already exists and you
need that description as a FAIRSCAPE RO-Crate, or you need the crate as
Croissant, a datasheet, a Workflow Run RO-Crate, a Frictionless package, or
PROV.

This package is the **create** step of FAIRSCAPE, next to
[fairscape_models](https://github.com/fairscape/fairscape_models).
Python 3.10 or newer. Apache-2.0.

## Import and export

Import and export are two steps, and the FAIRSCAPE RO-Crate is the file between them.

1. **Import** reads any file in the first table and writes one FAIRSCAPE RO-Crate (`ro-crate-metadata.json`). A datasheet, a Snakemake run, and an MLflow store all produce that same kind of crate.
2. **Export** reads that crate and writes one format from the second table. You choose the format when you export. The export reads the crate, so the format you write is a separate choice from the file you imported.

The export keeps the part of the crate that format can carry. A run's software and files show up in a Workflow Run RO-Crate. A crate's datasets show up in a Frictionless package. The commands are in [Run a conversion](#run-a-conversion).

### Import — any of these becomes a FAIRSCAPE RO-Crate

| You have | What you pass |
|---|---|
| **Datasheet for Datasets** | A written description of the dataset |
| **Frictionless** | A data package |
| **C2M2** | A CFDE datapackage |
| **REDCap** | A data dictionary, and the record export when you have it |
| **Workflow Run RO-Crate** | The RO-Crate profile for a run (CWL, Galaxy, and others) |
| **Cromwell** | A WDL workflow engine. The file is `metadata.json` |
| **Snakemake** | A workflow engine. The file is the reporter JSON |
| **Galaxy** | A workflow platform. An invocation export or a `.ga` file |
| **MLflow** | An experiment tracking store |
| **CPM** | A provenance crate and its PROV files |
| **track** | The files a Python script reads and writes |

### Export — write that crate as any of these

| You can write | What the file is |
|---|---|
| **Datasheet for Datasets** | The dataset description |
| **Frictionless** | A data package of the crate's datasets |
| **Workflow Run RO-Crate** | The run, with its software, inputs, and outputs |
| **PROV** | A provenance document |
| **Croissant** | MLCommons dataset metadata |

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
The quick start below shows the uv command and the pip command.

For a single run that keeps no environment on disk, put
`uv run --with fairscape-conversion` in front of that same line.

### pip

pip installs the same PyPI release. Create the virtual environment with
`python3`, the interpreter available before activation. After you activate
it, `python` is the interpreter inside `.venv`, and the later pip examples
use that.

```bash
python3 -m venv .venv              # Windows: py -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -U pip
python -m pip install fairscape-conversion
```

`.venv/bin/python` (Windows: `.venv\Scripts\python`) is that interpreter
if you call it by path.

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

pip. Create this environment with `python3` as well, then activate it
before the `python` lines:

```bash
python3 -m venv .venv              # Windows: py -m venv .venv
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

Convert a small datasheet. Do this after the PyPI install above.

Write the file and the output folder:

```bash
cat > datasheet.yaml << 'EOF'
name: example-dataset
title: Example dataset
description: A small datasheet, to try the converter.
license: CC0-1.0
EOF

mkdir -p my-crate
```

Run the conversion.

uv:

```bash
uv run python -m fairscape_conversion.core.cli convert d4d import datasheet.yaml my-crate/ro-crate-metadata.json
```

pip, after `source .venv/bin/activate`:

```bash
python -m fairscape_conversion.core.cli convert d4d import datasheet.yaml my-crate/ro-crate-metadata.json
```

The command prints `wrote my-crate/ro-crate-metadata.json`.

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

## Run a conversion

Four words, then the file to write. With uv, put `uv run` in front of
`python`. With pip, activate `.venv` first and run `python` as written here.

```bash
python -m fairscape_conversion.core.cli convert FORMAT import INPUT OUTPUT
python -m fairscape_conversion.core.cli convert FORMAT export INPUT OUTPUT
```

| Word | What you type |
|---|---|
| `FORMAT` | `d4d`, `snakemake`, `galaxy`, `redcap`, `frictionless`, `c2m2`, `wrroc`, `cpm`, or `croissant` |
| `import` | Read `INPUT` and write a FAIRSCAPE RO-Crate |
| `export` | Read a FAIRSCAPE RO-Crate and write the other format |
| `INPUT` | The file or folder you have |
| `OUTPUT` | Where to write the result. Leave it off and the result is printed |

A name ending in `.yaml` or `.yml` is YAML. Any other name is JSON. A successful
write prints `wrote OUTPUT`.

Add a flag after `OUTPUT` when you need one:

| Flag | Add it when |
|---|---|
| `--records FILE` | Importing REDCap, and you have the record-export CSV as well as the data dictionary |
| `--provn` | Exporting CPM as PROV-N. The usual CPM export is PROV-JSON |
| `--link-crate DIR` | An upstream crate already describes inputs of this run. Repeat the flag for another crate. `DIR` contains `ro-crate-metadata.json` |
| `--crate-dir DIR` | Relative paths in this crate should resolve from `DIR` |

`track` and `link` are separate commands, in the sections below. Cromwell and
MLflow are the Python calls in this section. Pass those two a path string:
the metadata file, or the tracking store.

### Datasheet — `d4d`

Import a Datasheet for Datasets. Export writes that datasheet again.

```bash
python -m fairscape_conversion.core.cli convert d4d import datasheet.yaml ro-crate-metadata.json
python -m fairscape_conversion.core.cli convert d4d export ro-crate-metadata.json datasheet-out.yaml
```

### Snakemake — `snakemake`

Snakemake is a workflow engine. Import the JSON from
`snakemake --reporter fairscape`.

```bash
python -m fairscape_conversion.core.cli convert snakemake import records.json ro-crate-metadata.json
```

### Galaxy — `galaxy`

Galaxy is a workflow platform. Import an invocation export (`.tar.gz`, `.zip`,
or a folder) or a `.ga` workflow file.

```bash
python -m fairscape_conversion.core.cli convert galaxy import invocation.tar.gz ro-crate-metadata.json
```

### REDCap — `redcap`

Import the data dictionary CSV. Add `--records` when you also have the
project's record export.

```bash
python -m fairscape_conversion.core.cli convert redcap import dictionary.csv ro-crate-metadata.json --records DATA.csv
```

### Frictionless — `frictionless`

Import a `datapackage.json`, or the folder that contains it. Export writes a
data package.

```bash
python -m fairscape_conversion.core.cli convert frictionless import ./package ro-crate-metadata.json
python -m fairscape_conversion.core.cli convert frictionless export ro-crate-metadata.json datapackage.json
```

### C2M2 — `c2m2`

Import a CFDE C2M2 datapackage folder. The command writes a crate folder
named `<slug>-crate` beside that datapackage, copies the source tables into
it, and prints the crate.

```bash
python -m fairscape_conversion.core.cli convert c2m2 import ./datapackage-dir
```

To choose the folder, call Python and pass `output_path`:

```python
from fairscape_conversion.plugins import c2m2

c2m2.convert("import", "./datapackage-dir", output_path="./crate")
```

### Workflow Run RO-Crate — `wrroc`

A Workflow Run RO-Crate is the RO-Crate profile for a workflow run (CWL,
Galaxy, and others). Pass its `ro-crate-metadata.json`. Import and export
both use that file.

```bash
python -m fairscape_conversion.core.cli convert wrroc import wrroc-metadata.json ro-crate-metadata.json
python -m fairscape_conversion.core.cli convert wrroc export ro-crate-metadata.json wrroc-metadata.json
```

### CPM — `cpm`

Import the crate directory. The PROV files sit beside
`ro-crate-metadata.json`, so the input is that directory. Export writes
PROV-JSON. Add `--provn` to write PROV-N.

```bash
python -m fairscape_conversion.core.cli convert cpm import ./crate-dir evi.json
python -m fairscape_conversion.core.cli convert cpm export ro-crate-metadata.json prov.json
python -m fairscape_conversion.core.cli convert cpm export ro-crate-metadata.json prov.provn --provn
```

### Croissant — `croissant`

Export a FAIRSCAPE RO-Crate as MLCommons Croissant.

```bash
python -m fairscape_conversion.core.cli convert croissant export ro-crate-metadata.json croissant.json
```

### Cromwell

Cromwell is a WDL workflow engine. `cromwell run -m metadata.json` writes the
file you import. Run this, with the path of that file:

```python
from fairscape_conversion.plugins import cromwell

cromwell.convert("import", "metadata.json", crate_dir="my-crate")
```

The call opens the file, reads each task, and can copy the submitted workflow
into `my-crate`. Add `schemas=True` to ask for an EVI Schema on each supported
data file. That needs the `schemas` extra from a clone:

```bash
uv pip install -e ".[schemas]"    # or: python -m pip install -e ".[schemas]"
```

`cromwell.convert` takes the path as a string. The `convert` command above
reads a `.json` file into a document first, so a Cromwell `metadata.json` goes
through this Python call.

### MLflow

Install `mlflow` (see [Install](#install)). Pass the tracking store and the
experiment name or id. For a directory such as `./mlruns`, set
`MLFLOW_ALLOW_FILE_STORE=true` in the environment. A `sqlite:///` URI needs
no extra variable.

```bash
MLFLOW_ALLOW_FILE_STORE=true python -c '
from fairscape_conversion.plugins import mlflow
mlflow.convert("import", "./mlruns", experiment="NAME", crate_dir="my-crate")
'
```

With uv, put `uv run` in front of `python`. `experiment` is the name or the
id. Pass `run_id="..."` to export one run and its nested children. Artifacts
are copied into `my-crate`. Pass `copy_artifacts=False` to point at the store
instead. `schemas=True` asks for an EVI Schema on each copied data file and
needs the `schemas` extra, same as Cromwell. Column schemas for logged dataset
inputs are written either way.

`mlflow.convert` takes the store as a string, the same way Cromwell takes the
metadata path.

## Track a Python run

`track` runs one script and appends that run to a crate. It is in this
repository (0.2.2). Install from a [clone](#clone-this-repository) first.

The command is:

```bash
python -m fairscape_conversion.core.cli track SCRIPT --crate-dir DIR -- SCRIPT_ARGS
```

Everything after `--` is passed to the script. With uv, put `uv run` in front
of `python`. This creates a script, a small input, and records the run:

```bash
mkdir -p data my-crate
printf 'raw\n' > data/raw.csv
cat > clean.py << 'EOF'
import sys
src, dst = sys.argv[1], sys.argv[2]
open(dst, "w").write(open(src).read().upper())
EOF

python -m fairscape_conversion.core.cli track clean.py --crate-dir my-crate -- data/raw.csv data/clean.csv
```

The command prints the computation it recorded, such as one input and one
output. The crate is `my-crate/ro-crate-metadata.json`. The script is copied
to `software/clean-<hash>.py` inside that directory. Run `track` again to
append another computation. An input the crate already describes reuses that
node.

| Flag | What you add |
|---|---|
| `--input FILE` | A file the capture misses. Repeat the flag for another file |
| `--link-crate DIR` | An upstream crate whose entities this run's inputs reuse |
| `--name TEXT` | Label for the run. The default is the script's file name |
| `--author TEXT` | Author. The default is the crate's author, or your username |
| `--keyword TEXT` | A keyword. Repeat the flag for another |
| `--start-clean` | Drop previous runs from the crate, then add this one |

The capture records `open` and `pathlib`. It also records pandas, numpy, and
matplotlib when those packages are installed. A script that reads and writes
no files prints `no file I/O detected; nothing was recorded`.

In Jupyter, from that same clone environment:

1. Load the extension.

```python
%load_ext fairscape_conversion.plugins.python
```

2. Run a cell that reads or writes a file. The cell is recorded in `my-crate`.

```python
%%fairscape track --crate-dir my-crate --name normalize
df = pd.read_csv("raw.csv")
df.to_csv("normalized.csv")
```

A cell that reads or writes nothing is left out of the crate.

## Link two crates

Use this when files this run reads are outputs another crate already
describes. `--link-crate` takes the directory that contains
`ro-crate-metadata.json`.

During a conversion, add the flag after `OUTPUT`:

```bash
python -m fairscape_conversion.core.cli convert snakemake import records.json ro-crate-metadata.json \
    --link-crate /path/to/upstream-crate
```

On a crate already written, run `link`. Add `-o OUT` to write a new file and
leave the original in place:

```bash
python -m fairscape_conversion.core.cli link ./crate-dir --link-crate /path/to/upstream-crate
```

Repeat `--link-crate` for another upstream crate. The command prints how many
inputs matched. With `convert` and no `--crate-dir`, relative paths resolve
from the output file's folder.

From Python, pass the same directory as `linked_crates`:

```python
from fairscape_conversion.plugins import mlflow

mlflow.convert(
    "import",
    "./mlruns",
    experiment="NAME",
    linked_crates=["/path/to/upstream-crate"],
)
```

From a clone, two worked pairs are already wired up. Run them from the
repository root:

```bash
python examples/import_snakemake_linked.py
python examples/import_mlflow_linked.py
```

Install `mlflow` and `pandas` before the MLflow one. In
`examples/linked-crates/nextflow-run`, `ro-crate-metadata.json` is under
`results/`. The write-up is
[`examples/linked-crates/`](examples/linked-crates).

## Examples

Run these from the repository root, after the
[clone install](#clone-this-repository).

uv:

```bash
uv run python examples/import_d4d.py
uv run python examples/run_all.py
```

pip, with `.venv` active:

```bash
python examples/import_d4d.py
python examples/run_all.py
```

`import_d4d.py` converts the datasheet shipped in the package and writes
`examples/out/d4d/`. `run_all.py` runs every example and prints pass or fail
for each one. Install `mlflow` and `pandas` before `run_all.py` when you want
the linked MLflow example in that run. Output goes to `examples/out/`.

The list of every script, including public Cromwell and Galaxy runs, is
[`examples/README.md`](examples/README.md).

[`examples/mlflow/mlflow_to_rocrate.ipynb`](examples/mlflow/mlflow_to_rocrate.ipynb)
trains a model and converts the store it wrote. The notebook also runs
`fairscape-cli`, which is a separate package, and it needs `mlflow`,
`scikit-learn`, `pandas`, and `jupyter`.

## Tests

From the clone.

uv:

```bash
uv pip install pytest
uv run python -m pytest
```

pip, with `.venv` active:

```bash
python -m pip install pytest
python -m pytest
```

Parity tests compare a few converters with the original implementations and
skip when those trees are not checked out beside this one.

## Add a format

A converter is a folder of two CSV mapping files and a small plugin class.
Copy [`plugins/example/`](plugins/example/) and follow
[`docs/NEW-PLUGIN.md`](docs/NEW-PLUGIN.md). The column reference is
[`MAPPING-SCHEMA.md`](MAPPING-SCHEMA.md). How a conversion runs is
[`docs/INTERNALS.md`](docs/INTERNALS.md).

## License

Apache-2.0.
