# Variant calling — a real Snakemake run

A Snakemake pipeline that actually runs, captured as an EVI RO-Crate. Three
samples' reads are aligned to a reference with **bwa-mem**, sorted and indexed
with **samtools**, called jointly with **bcftools**, and summarised into a
table and a plot. Twelve jobs over six rules, each rule in its own conda
environment.

Everything here was produced by [`run.sh`](run.sh) on the reads from
[snakemake-tutorial-data](https://github.com/snakemake/snakemake-tutorial-data)
— 654 variants called from ~34,000 real reads per sample.

```
data/samples/{A,B,C}.fastq ──bwa_map──▶ results/mapped/{A,B,C}.bam   (temp)
                                  └──samtools_sort──▶ results/sorted/{A,B,C}.bam
                                              └──samtools_index──▶ …bam.bai
   all three ──bcftools_call──▶ results/calls/all.vcf
                          ├──variant_summary──▶ results/calls/variant_summary.tsv
                          └──plot_quals──────▶ results/plots/quals.svg
```

## What is checked in

| File | What it is |
|---|---|
| `Snakefile`, `config.yaml`, `envs/`, `scripts/` | the workflow itself |
| `run/records.json` | what `snakemake --reporter fairscape` extracted from the finished run |
| `ro-crate-metadata.json` | the crate: 46 nodes — 13 Computations, 8 Software, 22 Datasets, 1 Schema |
| `croissant.json` | the Croissant view of it, written by [`../export_croissant_variants.py`](../export_croissant_variants.py) |
| `ro-crate-datasheet.html`, `ro-crate-preview.html`, `ro-crate-prov-graph.html`, `ai_ready_score.json`, `ro-crate-linkml.yaml` | what fairscape-cli derives from the crate — open them in a browser |
| `results/calls/*`, `results/plots/*` | the actual outputs: the VCF, the summary table, the quality histogram |

The reads (`data/`), the alignments (`results/sorted/`, `results/mapped/`) and
the conda environments (`.snakemake/`) are not checked in — `run.sh` fetches
and rebuilds them.

## Running it yourself

```bash
pip install snakemake snakemake-report-plugin-fairscape fairscape-cli
./run.sh
```

`run.sh` is two Snakemake invocations, and that split is the thing worth
understanding:

```bash
snakemake --cores 4 --use-conda          # 1. run the workflow
snakemake --reporter fairscape ...       # 2. report on the finished run
```

A Snakemake report plugin is a second, read-only pass over the DAG and the
`.snakemake` persistence metadata. `--reporter` on its own does **not** run
anything — it reports on what already ran, which is why the crate can describe
jobs that were already up to date.

## What the crate says

Each job becomes an EVI `Computation` carrying the resolved shell command, its
parameters, its start and end time, and edges to what it used and generated:

```
bcftools_call  --usedSoftware--> bcftools_call (the rule)
               --usedDataset--> genome.fa, A.bam, A.bam.bai, B.bam, …
               --generated---->  all.vcf
               --isPartOf----->  the run
```

Each rule becomes `Software` — its source as written in the Snakefile, and its
conda environment. `plot_quals` uses `script:` rather than `shell:`, so its
Software points at `scripts/plot_quals.py` and carries the script itself.

Two details worth pointing at when you show this to someone:

* `results/mapped/{A,B,C}.bam` are `temp()` outputs — Snakemake deleted them
  once they had been sorted. Their Datasets carry a `localPath` ("this was
  here when the run happened") instead of a `contentUrl`, which is exactly the
  distinction between a provenance record and a data package.
* `results/calls/variant_summary.tsv` gets an inferred EVI `Schema` — six
  typed columns — because the reporter ran with `--report-fairscape-schemas`.
  That is what lets the crate become Croissant and be read back by
  `mlcroissant`.

## Related

* [`../import_snakemake_variants.py`](../import_snakemake_variants.py) — the conversion on its own, from `run/records.json`
* [`../export_croissant_variants.py`](../export_croissant_variants.py) — this crate as Croissant, validated with MLCommons' loader
* [`../wdl-variant-calling/`](../wdl-variant-calling) — the same analysis in WDL, run by Cromwell
