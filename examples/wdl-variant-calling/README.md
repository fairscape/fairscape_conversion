# Variant calling — a real Cromwell/WDL run

The same analysis as [`../snakemake-variant-calling`](../snakemake-variant-calling),
written as WDL and executed by **Cromwell 92**: `BwaMem` scattered over three
samples, `SamtoolsSort` and `SamtoolsIndex` per shard, then a `BcftoolsCall`
gather, a summary table and a plot. Twelve calls over six tasks, finished
`Succeeded` in 59 seconds.

```
scatter (sample in zip(sample_names, sample_reads)):
    BwaMem  ──▶ SamtoolsSort ──▶ SamtoolsIndex
                     └──────────────┐
BcftoolsCall (all three) ──▶ all.vcf ├──▶ VariantSummary ──▶ variant_summary.tsv
                                     └──▶ PlotQuals      ──▶ quals.svg
```

## What is checked in

| File | What it is |
|---|---|
| `variant-calling.wdl`, `inputs.json`, `options.json`, `cromwell.conf` | the workflow and how it was launched |
| `run/metadata.json` | what Cromwell wrote with `-m` — every call's command, inputs, outputs, timings and status |
| `ro-crate-metadata.json` | the crate: 47 nodes — 13 Computations, 8 Software, 23 Datasets, 1 Schema |
| `ro-crate-datasheet.html`, `ro-crate-preview.html`, `ro-crate-prov-graph.html`, `ai_ready_score.json`, `ro-crate-linkml.yaml` | derived from the crate by fairscape-cli |
| `results/all.vcf`, `results/variant_summary.tsv`, `results/quals.svg` | the final outputs Cromwell copied out (`final_workflow_outputs_dir`) |

Cromwell's execution root (`cromwell-executions/`), the reads (`data/`), the
BAMs and the Cromwell jar are not checked in — `run.sh` rebuilds them.

## Running it yourself

```bash
./run.sh          # fetches the reads and the Cromwell jar on first use
```

Needs a JVM and the tools on PATH — bwa, samtools, bcftools, and a python3
with pysam and matplotlib. The tasks declare no `docker:` runtime attribute,
so they run as plain shell scripts on Cromwell's local backend and nothing
here needs Docker. On a Docker-enabled backend you would add the attribute and
Cromwell would record the image digest it actually pulled in
`dockerImageUsed` — which the crate then carries as `containerImage` on every
Computation.

`run.sh` is two steps:

```bash
java -jar cromwell.jar run variant-calling.wdl -i inputs.json -m run/metadata.json
python convert.py           # metadata.json -> ro-crate-metadata.json
```

Unlike Snakemake, nothing has to be installed into the engine: Cromwell
already writes the run's full metadata, and the cromwell plugin reads that
file directly.

## What the crate says

Scatter shards stay separate Computations, so the fan-out is visible:

```
BwaMem (shard=0)   --usedDataset--> genome.fa + its bwa index + A.fastq
                   --generated---->  A.bam
BcftoolsCall       --usedDataset--> the three sorted BAMs, their indexes, genome.fa
                   --generated---->  all.vcf
```

Provenance falls out of exact path matching: Cromwell records each call's
inputs *before* localization, so a consumer's input path string is the same
string as its producer's output path.

Two details worth pointing at:

* The submitted WDL and inputs JSON are written into the crate and registered
  as Software and Dataset, so the crate carries the exact workflow text that
  ran — not a reference to a file that may have changed since.
* Every output path lands as a `contentUrl` under `cromwell-executions/…`,
  which is where Cromwell actually left it. `results/` holds the copies
  Cromwell made on the way out; they are the same bytes.

## Related

* [`../import_cromwell_variants.py`](../import_cromwell_variants.py) — the conversion on its own, from `run/metadata.json`
* [`../export_croissant_variants.py`](../export_croissant_variants.py) — the Snakemake crate as Croissant; the same script works on this crate once you have run it (its TSV lives under `cromwell-executions/`)
* [`../snakemake-variant-calling/`](../snakemake-variant-calling) — the same analysis in Snakemake
