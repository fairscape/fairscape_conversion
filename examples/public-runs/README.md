# Public runs

Real workflow executions by other people, as their engines wrote them, for
checking the converters against runs nobody here controlled. Nothing was
edited; the files are what the sources publish. Each is small enough to keep
here (the largest is 1 MB).

[`../import_cromwell_public.py`](../import_cromwell_public.py) and
[`../import_galaxy_public.py`](../import_galaxy_public.py) convert every file
below and then check the crate's computation graph against the workflow
definition inside the run — the WDL a Cromwell run submitted, the `.ga` in a
Galaxy export — so the question "does the provenance say what the pipeline
says?" is answered by the script, not by eye.

## cromwell/ — `metadata.json` as written by `cromwell run -m` / the Cromwell API

| File | Pipeline | Backend | Source | Licence |
|---|---|---|---|---|
| `encode-atac-seq.metadata.json` | [ENCODE ATAC-seq pipeline](https://github.com/ENCODE-DCC/atac-seq-pipeline), 12 calls incl. scatter shards, Cromwell 59 | Google Cloud (Caper) | [kundajelab/neuro-variants](https://github.com/kundajelab/neuro-variants) `preprocess/0_process_data/ameen_2022/pipeline_metadata_jsons/ameen_2022.PC.metadata.json` | MIT |
| `encode-mirna-seq.metadata.json` | [ENCODE miRNA-seq pipeline](https://github.com/ENCODE-DCC/mirna-seq-pipeline), 2 replicates, Cromwell 42 | Google Cloud (Caper) | [ENCODE-DCC/accession](https://github.com/ENCODE-DCC/accession) `tests/data/mirna_replicated_metadata.json` | MIT |
| `broad-subworkflow-hello.metadata.json` | a one-call subworkflow | Google Cloud (PAPI) | [broadinstitute/cromwell](https://github.com/broadinstitute/cromwell) `scripts/metadata_comparison/test/resources/subworkflow_hello_world_metadata.json` | BSD-3 |

Every input and output is a `gs://` object, so the crates carry remote
`contentUrl`s and nothing is downloaded. The ATAC run is the closest public
stand-in for a Terra / AnVIL submission: same engine, same cloud backend,
same metadata shape the Terra API returns.

Two things about the conversion worth knowing when you read these crates:

* a retried call collapses to its last attempt (one computation per shard);
* a subworkflow call is flattened — its inner calls join the parent run and
  the subworkflow itself gets no node.

## galaxy/ — `.rocrate.zip` as written by Galaxy's *export invocation*

| File | Workflow | Galaxy | Source | Licence |
|---|---|---|---|---|
| `FeS2-Analysis.rocrate.zip` | FeS2 EXAFS analysis with Larch (Athena → FEFF → select paths → Artemis), 6 steps | usegalaxy.eu 24.1 | [Zenodo 13987511](https://zenodo.org/records/13987511), Nieva de la Hidalga | CC-BY-4.0 |
| `N2O-LaMnO3-Figs6.rocrate.zip` | N2O decomposition on LaMnO3, figure 6: one Athena collection, three `__EXTRACT_DATASET__` steps, three Artemis fits, 11 steps | usegalaxy.eu 24.1 | [Zenodo 19694805](https://zenodo.org/records/19694805), Liborio, Nieva de la Hidalga, Austin | CC-BY-4.0 |

Each zip holds Galaxy's Workflow Run RO-Crate (one `CreateAction` for the
whole invocation, which the `wrroc` plugin reads) *and* Galaxy's model store
(`jobs_attrs.txt`, `datasets_attrs.txt`, …), which the `galaxy` plugin
reads to get every job. The second run is here because it exercises
`__EXTRACT_DATASET__`: the copy a step pulls out of a collection shares the
original's dataset uuid, so it is one node with one producer, and the copy
step is pass-through (it consumes, it does not generate).
