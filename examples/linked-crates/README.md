# Linked crates — two independent runs, one provenance chain

Two runs that never heard of each other, each with its own crate, and the
second one's inputs were the first one's outputs. This folder shows how the
second crate is made to *know* that, and how the evidence graph then runs
straight through both.

```
nextflow-run/results/          crate A: nf-fairscape wrote it when the pipeline ran
   letters.txt -> reversed.txt -> first_half.txt + second_half.txt

mlflow-analysis/               crate B: an MLflow run that scored the two halves
   analyze.py                  reads A's first_half.txt / second_half.txt, logs them as inputs
   crate/                      B converted with linked_crates=[A]

snakemake-count/               crate C: a one-rule Snakemake run over another pipeline's table
   Snakefile                   reads ../../snakemake-variant-calling/results/calls/variant_summary.tsv
   run/reporter-crate.json     what the FAIRSCAPE reporter wrote, untouched
   ro-crate-metadata.json      the same crate after `fairscape_conversion link`
```

Run either from the repo root:

```bash
python examples/import_mlflow_linked.py       # A + B   (--rerun re-executes analyze.py; needs mlflow, pandas)
python examples/import_snakemake_linked.py    # C linked to ../snakemake-variant-calling
```

Then open `mlflow-analysis/crate/ro-crate-evidence-graph.html` or
`snakemake-count/ro-crate-evidence-graph.html`.

## What the link is

A converted crate mints its own identifiers. For a file it only *consumed*,
that produces a fresh, producer-less Dataset — the converter has no way to
know another crate already describes the file. The linking pass
(`core/linking.py`) fixes exactly that, after the conversion, by reading the
finished crate and asking each *linked crate* on disk whether it already
describes the file:

| tries, in order | how |
|---|---|
| path | the same absolute file (`contentUrl` resolved against each crate's folder, or `localPath`) |
| md5 | both sides declare a checksum and they agree |
| directory | the file sits inside a directory the upstream crate describes as one Dataset; the node keeps its own id and gains `isPartOf` → that directory |

On a hit the consumer's node becomes a **stub** of the upstream entity:

```json
{"@id": "ark:59853/dataset-first-half-txt-e00f213",      <- the upstream's ARK, not re-minted
 "@type": ["prov:Entity", "https://w3id.org/EVI#Dataset"],
 "name": "first_half.txt",
 "description": "File 'first_half.txt' produced by the Nextflow workflow run 'main.nf'",
 "localPath": "/…/linked-crates/nextflow-run/results/first_half.txt",
 "isPartOf": [{"@id": "ark:59853/rocrate-main-nf-600fc41"}]}
```

No `generatedBy`, no copy of the upstream Computation: the producer lives in
the upstream crate. The upstream crate itself appears once, as a pointer:

```json
{"@id": "ark:59853/rocrate-main-nf-600fc41",
 "@type": ["Dataset", "https://w3id.org/EVI#ROCrate"],
 "name": "letters-chain demonstration crate",
 "hasPart": [{"@id": "ark:59853/dataset-first-half-txt-e00f213"}, …],   <- just the entities stubbed here
 "ro-crate-metadata": "../../nextflow-run/results/ro-crate-metadata.json",
 "localPath": "/…/linked-crates/nextflow-run/results/ro-crate-metadata.json"}
```

`ro-crate-metadata` is the same field a release crate uses for its
constituents. The difference is that the consumer's root does **not** list
this node in its own `hasPart`: it is a pointer to where an input came from,
not a part of this crate. Every reference to the old id in the crate
(`usedDataset`, `hasPart`, `EVI:inputs`) is rewritten to the upstream id.

## What follows the pointer

`fairscape-artifacts` loads linked crates the way it loads a release's
sub-crates, layers their nodes under the consumer's (the upstream's own copy
of the shared entity wins over the stub, and it is the copy that carries
`generatedBy`), and the evidence walk keeps going. Nodes that came through a
pointer carry `"crate": {"@id", "name"}` in the graph JSON; the datasheet
lists the linked crates in its overview and names the upstream crate as the
origin of the inputs. A missing upstream is a warning, and the graph then
ends at the stub.

## Three ways to run the pass

```python
crate = mlflow.convert("import", tracking_uri, ..., linked_crates=["/path/to/crateA"])
```
```bash
fairscape_conversion convert snakemake import records.json out.json --link-crate /path/to/crateA
fairscape_conversion link /path/to/crateB --link-crate /path/to/crateA        # any crate, after the fact
```

The option is honoured by every importer that goes through `PluginBase`,
because the pass reads the finished crate rather than the plugin's records.
The one thing an importer must do to take part is put a resolvable
`contentUrl` or `localPath` on the nodes it consumed; the MLflow plugin
now writes a logged dataset's source path as `localPath` for that reason.

## What is not linked, on purpose

* `vowels.txt` in the MLflow example came from nowhere: it stays a plain
  input.
* Snakemake itself is described by both Snakemake crates under the same
  deterministic ARK. That is two descriptions of one tool, not one crate
  taking it from the other, so Software is never claimed by id.
* A crate's own outputs are never claimed by an upstream crate
  (`only_inputs=True`).
