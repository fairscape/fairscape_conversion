# Examples

One runnable example per conversion, each on real input that ships with the
package. Every script prints what went in, what came out, and — where the
conversion is deterministic — whether it matches the plugin's reviewed
`golden.json`. Nothing needs installing first: the scripts bind
`fairscape_conversion` to this checkout.

```bash
python examples/run_all.py            # all twelve, with a pass/fail table
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

## Real runs, end to end

The examples above run on fixtures so they finish instantly. These three run
on two pipelines that were actually executed — the same variant-calling
analysis written twice, once in Snakemake and once in WDL, on real sequencing
reads. Both workflow directories are checked in with their crates, their
datasheets and their outputs, so you can open them without running anything.

| Example | What it converts | The run it came from |
|---|---|---|
| [`import_snakemake_variants.py`](import_snakemake_variants.py) | 12 jobs over 6 rules, bwa → samtools → bcftools | [`snakemake-variant-calling/`](snakemake-variant-calling) |
| [`import_cromwell_variants.py`](import_cromwell_variants.py) | 12 Cromwell calls, 3 of them scatter shards | [`wdl-variant-calling/`](wdl-variant-calling) |
| [`export_croissant_variants.py`](export_croissant_variants.py) | that crate's variant table as Croissant, then read back with MLCommons' own `mlcroissant` — 654 rows | ← the Snakemake crate |

Together they are the whole chain on one analysis: **pipeline → run records →
EVI crate → Croissant → rows back out**. Each workflow folder has a `run.sh`
that reproduces it from nothing (it fetches ~18 MB of reads; the WDL one also
fetches the Cromwell jar), and a README explaining what the crate says about
the run.

## Two runs, one chain — linked crates

| Example | What it shows |
|---|---|
| [`import_mlflow_linked.py`](import_mlflow_linked.py) | an MLflow run over a Nextflow pipeline's outputs, converted with `linked_crates=[…]`: its inputs become the Nextflow crate's entities, and the evidence graph runs through both |
| [`import_snakemake_linked.py`](import_snakemake_linked.py) | the same pass run standalone (`fairscape_conversion link`) over a crate the Snakemake reporter wrote, linking it to the variant-calling crate |

The convention — what a stub is, what the pointer is, what is deliberately
left unlinked — is written up in [`linked-crates/README.md`](linked-crates/README.md).

## The full walk-through

**[`mlflow/mlflow_to_rocrate.ipynb`](mlflow/mlflow_to_rocrate.ipynb)** is the
end-to-end one: it trains a scikit-learn model with MLflow tracking, converts
the store it just created, validates the crate, and renders its datasheet and
provenance graph inline. It ends with [`mlflow/pipeline/`](mlflow/pipeline), a
three-step prepare → train → evaluate pipeline whose evaluate run `usedMLModel`
the trained model. Both notebook and crates are checked in with their outputs.
See [`mlflow/README.md`](mlflow/README.md).

Every script on this page finishes instantly — the real-run examples convert
records that are checked in, not pipelines they re-execute. The two things
that start from nothing are that notebook (needs `mlflow`, `scikit-learn` and
`pandas`) and the two `run.sh` scripts in the variant-calling folders (need
Snakemake, or a JVM, plus the bioinformatics tools).

## Reading them

Each script is short and its docstring is the explanation — start with the
docstring, then the ~15 lines under it. Shared plumbing (path setup, the
node/edge printers, the golden and entity checks) lives in
[`_example.py`](_example.py) so
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
