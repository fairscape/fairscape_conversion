# fairscape_conversion — bug hunt report (2026-10-12)

Every converter in this repo was run on real, valid inputs. The inputs came from:
- the bridge2ai D4D datasheets
- the ResearchObject workflow-run-crate examples
- 127 IWC Galaxy workflows and the Zenodo Galaxy, sapporo and pfhub crates
- the Frictionless example packages and datahub packages
- the HMP C2M2 submission
- the REDCapR and redcapAPI projects
- new Cromwell 92 and Snakemake 9 runs
- MLflow 3.16 stores
- scripts run through `track`

Each bug below was reproduced with an actual run. The code was not changed.

**Repro scripts.** IDs refer to the sections below. The paths in each bug are relative to
`/tmp/claude-1000/-home-oj-fairscape/af818fed-1e2a-41b0-b0c3-26e5b35d996e/scratchpad/bughunt/`, which holds the repro scripts, downloaded inputs and outputs. That directory is session scratch space and may be cleaned up, so copy anything you want to keep.

**Severity labels:**
- **breaking**: an exception, or an invalid output, on valid input
- **wrong-provenance**: provenance links are wrong, missing or dangling
- **mistranslation**: data is dropped or altered
- **minor**

## Priorities

| # | Bug | Severity |
|---|-----|----------|
| D2 | d4d import requires `license`; 21 of 26 real bridge2ai datasheets fail | breaking |
| D1 / C7 | croissant export crashes on every d4d-derived crate, including AI-READI | breaking |
| W1 | wrroc import fails when `license` is an `@id` ref; this hits every official WRROC profile example | breaking |
| G1 / F6 | galaxy (no user) and frictionless (no contributors) imports silently write invalid crates (`runBy` / `author` missing) | breaking |
| CPM2 / CPM3 | cpm export writes PROV that the `prov` library rejects (undeclared `dct:`, raw URLs as qualified names) | breaking |
| F1 | frictionless import crashes when `schema` or `dialect` is given as a path or URL | breaking |
| C5 | `--link-crate` crashes wrroc and d4d import | breaking |
| C1 / C3 | linking matches on ARK alone, and ARKs hash only the relative path, so unrelated projects' files and roots get linked | wrong-provenance |
| C2 | linking folds the consumer's workflow/rule Software into an arbitrary upstream rule (they share the Snakefile path) | wrong-provenance |
| CW1 / CW2 | cromwell ARK collisions silently drop scatter shards and glob outputs | wrong-provenance |
| P1 / P5 | `track` links reads to stale file versions, and links edited scripts to the old code's Software | wrong-provenance |
| M1 | mlflow aliases a run's input dataset to an artifact logged by a *later* run | wrong-provenance |
| W4 | wrroc export gives PropertyValues colliding `@id`s, so a run gets another run's parameter value | wrong-provenance |
| C2M2-3 / C2M2-4 | c2m2 merges entities across `id_namespace`s; the conversion Computation claims it generated the DCC's data files | wrong-provenance |
| CPM1 | cpm import turns PROV timestamps into Dataset entities and ignores activity times and `wasAssociatedWith` | wrong-provenance |

There are about 65 verified bugs in total:

| Area | Bugs |
|------|------|
| core / linking | 8 |
| d4d / croissant | 14 |
| frictionless / c2m2 / redcap | 17 |
| galaxy / wrroc / cpm | 11 |
| mlflow / track | 9 |
| snakemake / cromwell | 6 |

A recurring root cause runs through C1, C3, CW1, CW2, D4 and C2M2-3. The ARK source omits a disambiguator: the namespace, the parent shard, the absolute path or the UUID. The engine's first-writer-wins dedup in `core/engine.py` then drops the colliding entity silently. A duplicate-ARK warning in the engine would surface all of them.

## Core, linking and cross-format chaining

Scripts: `bughunt/core/` (S below).

### C1. Linking matches on ARK alone; an unrelated file is claimed as another project's output — wrong-provenance
- Conversion: `convert snakemake import ... --link-crate`, and the same step in `link`.
- Repro: `S/idcollide/make.py`, then from `S/idcollide`:
  `python -m fairscape_conversion.core.cli convert snakemake import projA/records.json projA/ro-crate-metadata.json`
  `python -m fairscape_conversion.core.cli convert snakemake import projB/records.json projB/ro-crate-metadata.json --link-crate projA`
- Observed: projA and projB are unrelated projects. Each has its own `results/table.tsv`, and the two files differ. Both crates mint `ark:59853/dataset-table-tsv-0c3dbf6` for it. With `--link-crate`, projB's own input is matched by `@id` and replaced by a stub of projA's generated output. The stub has `isPartOf` projA and the description "produced by…", but its `localPath` is projB's file.
- Expected: no match, because the path and content differ. Distinct files should get distinct ARKs.
- Code: `core/linking.py:464-472` matches on the id without checking path or md5. Root cause: `plugins/snakemake/__init__.py:90-92` hashes only the relative `normpath(path)`, and `plugins/python/__init__.py:78-83` does the same for inputs.

### C2. Shared Snakefile/WDL path folds the consumer's workflow and rule Software into the wrong upstream rule — wrong-provenance
- Conversion: `--link-crate` and `link`.
- Repro: run `S/idcollide/make.py`, then `S/idcollide/softfold.py`. The script runs a second invocation of projA that consumes projA's output and is linked to projA.
- Observed: the consumer's workflow Software `software-snakefile-…` and its rule `software-finalise-…` are both replaced by the upstream rule `software-make-table-66a522f`. As a result, `finalise` has `usedSoftware -> make_table`.
- Cause: every rule and task Software node shares the Snakefile/WDL `contentUrl`. In `_index_paths`, the last node whose file exists wins (`core/linking.py:239-241`). Software is matched by path even though id matching deliberately excludes it (`linking.py:464`). Which node wins depends on the data: in `examples/snakemake-variant-calling`, `Snakefile` maps to the `variant_summary` rule. `S/dup_paths.py` lists every affected crate.

### C3. Upstream and consumer root ARKs collide; upstream pointer lost, stubs point at the consumer's own root — wrong-provenance
- Repro: `S/idcollide/samroot.py` runs the same Snakefile twice under the same run name, with run 2 linked to run 1.
- Observed: both roots are `ark:59853/rocrate-project-a-26d4ad5`. No pointer node is written, because the crate stub is dropped as "already emitted". The stub's `isPartOf` therefore resolves to the consumer crate itself.
- Code: `core/linking.py:537` and the rebuild at `550-556` do not handle `lc.root_id == root_id`. The root ARK is minted only from the run name and Snakefile path (`plugins/snakemake/__init__.py:77`; cromwell `:94` does the same).

### C4. Stub drops the consumer's inverse edges (`datasetUsedBy` / `usedByComputation`) — wrong-provenance
- Repro: `S/inverse/run.py` links `examples/linked-crates/snakemake-count/run/reporter-crate.json` to `snakemake-variant-calling`.
- Observed: before linking, `variant_summary.tsv` has `datasetUsedBy` pointing at its 2 computations. After linking, the stub has `datasetUsedBy=None`, while both computations still list it in `usedDataset`. The checked-in `examples/linked-crates/snakemake-count/ro-crate-metadata.json` shows the same loss.
- Code: `core/linking.py:332` skips the consumer-side fields in `_EDGE_FIELDS`. Dropping the upstream values is correct, but the consumer's own edges should be kept.

### C5. `--link-crate` / `--crate-dir` crash wrroc and d4d import — breaking
- Repro: `python -m fairscape_conversion.core.cli convert wrroc import plugins/wrroc/input.json out.json --link-crate S/idcollide/projA` fails the same way for d4d.
- Observed: `TypeError: convert() got an unexpected keyword argument 'linked_crates'`. The docstring in `core/cli.py` says `--link-crate` works "on any import".
- Code: `plugins/wrroc/__init__.py:22` and `plugins/d4d/__init__.py:21` have fixed signatures, and `core/cli.py:116-133` forwards the options without checking.

### C6. frictionless import silently skips linking: `crate_dir` is swallowed by extraction — wrong-provenance
- Repro: `S/frictionless_link.py`, or from the CLI: `convert frictionless import projA/results projA/results/fl-crate.json --link-crate projA --crate-dir projA/results`
- Observed: 0 matches. Calling `link_crate` directly on the same crate with the same `crate_dir` matches `table.tsv` by path.
- Code: `plugins/frictionless/__init__.py:280-282` pops `crate_dir` into `extract_opts`, so `PluginBase.import_` (`core/plugin.py:119`) receives `crate_dir=None`. cromwell and mlflow copy it back; frictionless doesn't. `plugins/galaxy/__init__.py:213-215` uses the same pop pattern but was not run.

### C7. d4d import → croissant export crashes — breaking (chaining)
- Repro: `S/d4d_to_croissant.sh`
- Observed: `ValidationError CroissantDataset rai:dataCollection: Input should be a valid string`. The d4d crate stores `rai:dataCollection` as a list of tagged strings, but `plugins/croissant/properties.csv:16` maps it as a scalar.
- Same chain: Croissant `creator[].name` values are raw tagged strings, e.g. `"Field: creators | name: Aaron Lee | description: ..."`.
- This is the only failing pair in the 23-crate × 5-exporter matrix (`S/matrix.py`).

### C8. Schema inference mis-types real CSV columns — mistranslation
- Repro: run `S/schema/mk.py`, then `S/schema/infer.py t.csv t.tsv t.csv.gz t.txt`.
- Observed:
  - A zip-code column (`02134,00501`) is inferred as `integer`, so the leading zeros are lost.
  - An all-empty column is listed in `required`.
  - `.csv.gz` files and tab-separated `.txt` files get no schema and no note.
- Code: `core/schemas.schema_node` → `fairscape_models.schema.infer_schema`. The fix is probably in fairscape_models.

### Minor (core)
- The CLI shows a raw traceback in five cases:
  - output into a missing directory: `FileNotFoundError` (`cli.py:79-86`)
  - `--link-crate` with no value: `IndexError` (`cli.py:101`)
  - `--link-crate some.zip`: `UnicodeDecodeError`, because zipped crates are unsupported (`linking.py:213`)
  - `convert cromwell import metadata.json`: `KeyError`. cromwell is not in `PATH_SOURCE_IMPORTS` (`cli.py:68`), although the README routes it through Python.
  - `convert mlflow import mlruns/`: `IsADirectoryError`, for the same reason.
- `cpm export --provn` to a `.yaml` output writes the PROV-N text as a YAML-quoted string.
- Possibly by design: run-level Computations list `generated` outputs whose `generatedBy` points only at the job (cromwell, galaxy, snakemake).

Checked and fine:
- All 23 example crates validate against ROCrateV1_2.
- No duplicate `@id`s, and no dangling refs except c2m2's `isPartOf ark:59853/mini`.
- Every other import × export pair runs.
- `link` is idempotent.
- Relative paths outside the crate link correctly.
- Within one crate, ARKs don't collide on case, unicode or same name in different folders.
- Schema inference handles big ints, booleans, scientific notation, dates and TSV.
## D4D (import / export) and Croissant (export)

Scripts are in `bughunt/d4d-croissant/` (S below): `scripts/d4d_probe.py`, `scripts/croissant_probe.py`, `scripts/batch_d4d.py` and `scripts/mlc_validate.py`. Real D4D inputs come from a clone of bridge2ai/data-sheets-schema in `S/dl/data-sheets-schema`. mlcroissant is installed in `S/venv-mlc`.

Several of the Croissant bugs are in `fairscape_models/conversion/` (`mapping/croissant.py`, `mapping/utils.py`, `models/croissant.py`). The croissant plugin hands its work to that code unchanged.

### D1. Croissant export crashes on every d4d-derived crate, and on RAI list/str shape mismatches. Severity: breaking
- Repro: `python -m fairscape_conversion.core.cli convert croissant export examples/out/d4d/ro-crate-metadata.json out.json`. Also `S/scripts/croissant_probe.py`, block 1.
- Observed: `ValidationError CroissantDataset rai:dataCollection: Input should be a valid string`. It fails on the shipped AI-READI crate and on all 11 real D4D files that got through import.
- Which field shapes break it:
  - A list crashes in `dataCollection`, `dataCollectionMissingData`, `dataCollectionRawData`, `dataAnnotationProtocol` and `dataImputationProtocol`.
  - A plain string crashes in `dataCollectionType`, `dataPreprocessingProtocol`, `dataAnnotationPlatform` and `dataAnnotationAnalysis`.
  - The crate model allows `Union[str, List[str]]` for all of these (`fairscape_models/rocrate.py:204-246`).
- Code: `fairscape_models/conversion/models/croissant.py:118-127` declares strict types, and `mapping/croissant.py:297-308` passes the values through as-is.
- Hidden behind the crash: Croissant `creator` names would be tagged strings such as `"Field: creators | name: Aaron Lee | description: ..."`.

### D2. d4d import rejects any valid datasheet with no `license`. Severity: breaking
- Repro: `python -m fairscape_conversion.core.cli convert d4d import S/dl/data-sheets-schema/src/data/examples/valid/Dataset-minimal.yaml out.json`. Also `S/scripts/batch_d4d.py`.
- Observed: `ValidationError ROCrateV1_2: license Field required`. 21 of 26 real bridge2ai D4D files fail, including the schema repo's own valid examples and the curated AI_READI, CM4AI and VOICE files.
- Expected: `license` is optional in D4D. Name, description, version and author already get defaults; license doesn't.
- Code: `plugins/d4d/impl.py:203-208` (`_map_root`). The error is raised at `impl.py:179-181`.

### D3. d4d import crashes when `external_resources` is a list of URL strings. Severity: breaking
- Repro: `S/scripts/d4d_probe.py` T3.
- Observed: `AttributeError: 'str' object has no attribute 'get'`. The D4D slot description explicitly allows a list of URL strings.
- Code: `plugins/d4d/impl.py:101` (`_build_digital_object` assumes a dict). The values come from `impl.py:161-165`.

### D4. Multiple `external_resources` / `use_repository` / `resources` items without `id` collapse into one. Severity: mistranslation, silent data loss
- Repro: `S/scripts/d4d_probe.py` T2.
- Observed: two resources (a.org, b.org) become a single `_:external_resources` DigitalObject that holds only a.org.
- Code: `plugins/d4d/impl.py:101` falls back to `f"_:{spec['d4d_field']}"`, so every item gets the same id. First-writer-wins dedup in `core/engine.py:216-219` then drops the rest.

### D5. `was_derived_from` becomes a plain or comma-joined string, not a provenance link. Severity: wrong-provenance
- Repro: `S/scripts/d4d_probe.py` T4.
- Observed:
  - One value gives `derivedFrom: "https://doi.org/10.1/parent"`.
  - Two values give `derivedFrom: "https://doi.org/10.1/p1, https://doi.org/10.1/p2"`.
  - No `{"@id": ...}` reference is produced in either case.
- Code: the `was_derived_from` row in `plugins/d4d/properties.csv` uses `parse_scalar` (`plugins/d4d/parsers.py:26-31`).

### D6. `version_access` is lost or overwrites `version`. Severity: mistranslation
- Repro: `S/scripts/d4d_probe.py` T6, and the real file `data/test/CM4AI_merge_test.yaml`.
- Observed:
  - With both fields present, `version_access` disappears.
  - With only `version_access`, the crate gets `version = "Field: version_access | description: ..."`, which then exports back under `version`.
- Code: the scalar reduce at `plugins/d4d/impl.py:131-138`, and the `version_access → version` mapping row.

### D7. Values containing " | ", " ; " or ": " are corrupted on round trip. Severity: mistranslation
- Repro: `S/scripts/d4d_probe.py` T7. The creator description `"Role: PI | lab lead ; also curator"` comes back as `"Role: PI"`.
- Code: `core/roundtrip.py:62-99`:
  - `tag_item` doesn't escape the delimiters.
  - `untag_item` drops segments at lines 93-96.
  - `plugins/d4d/parsers.py:89` also calls `split(ITEM_SEP)`.

### D8. Nested objects, lists and booleans come back as strings. Severity: mistranslation, lossy round trip
- Repro: `S/scripts/d4d_probe.py` T8.
- Observed:
  - `involves_human_subjects: true` comes back as `'True'`.
  - `irb_approval: [a, b]` comes back as `'a, b'`.
  - `affiliations: [{id, name}]` comes back as `'id: o1, name: UVA'`.
- Code: `core/roundtrip.py:46-56` (`flatten_value`) and `untag_item`.

### D9. Valid D4D slots are silently dropped on import. Severity: mistranslation, partly provenance
- Repro: `S/scripts/d4d_probe.py` T5.
- Observed:
  - These slots vanish from the crate: `citation`, `parent_datasets`, `related_datasets`, `splits`, `variables`, `notes` and `total_size_bytes`.
  - These are never mapped: `conforms_to*`, `file_collections`, `compression`, `is_tabular`, `data_governance` and `source_caveats`.
  - `parent_datasets` and `related_datasets` are dataset-to-dataset provenance.
  - DigitalObjects are keyed on `distributions`, which isn't a slot in the current D4D schema. Download URLs actually live in `distribution_formats[].download_url` and only end up as tagged strings in `evi:formats`.
- Code: `plugins/d4d/properties.csv` and `entities.csv`. The gaps were found by diffing them against `data_sheets_schema_all.yaml`.

### D10. `created_by` alone is exported back as `creators`. Severity: minor
- Repro: `S/scripts/d4d_probe.py` T9 and T10.
- Observed:
  - `created_by: "Jane Doe"` exports as `creators: [{description: "Jane Doe"}]`.
  - When both fields are present, `author` mixes a tagged string with a plain name.
- Code: `plugins/d4d/parsers.py:94-95`.

### D11. Croissant export drops `rai:dataSocialImpact`, `rai:machineAnnotationTools`, `rai:annotationsPerItem` and `datePublished`. Severity: mistranslation
- Repro: `S/scripts/croissant_probe.py` block 2. None of the 23 example exports has `datePublished`, and mlcroissant warns about it.
- Code:
  - `fairscape_models/conversion/mapping/croissant.py:308` reads `rai:socialImpact`, but the crate alias is `rai:dataSocialImpact` (`rocrate.py:253`).
  - The other three have no mapping at all.
  - `plugins/croissant/properties.csv` repeats the same mapping rows.

### D12. RecordSet `key` comes from JSON-Schema `required` instead of the primary key, and can dangle. Severity: mistranslation
- Repro: `S/scripts/croissant_probe.py` blocks 5 and 6, run on `examples/out/frictionless`.
- Observed:
  - With `primaryKey [county_fips, week_start]`, the key comes out as `[county_fips, week_start, cases]`.
  - A required column `county-name` gives the key `.../county-name`, but the field `@id` is `.../county_name`, so the key points nowhere.
  - `foreignKeys` are not mapped to `references`.
- Code: `fairscape_models/conversion/mapping/croissant.py:268`. The key uses `format_name`, while field ids use `sanitized_path` (line 183).

### D13. Duplicate FileObject `@id`s when two datasets share a final path segment. Severity: invalid output
- Repro: `S/scripts/croissant_probe.py` block 4.
- Observed: `.../a/data.csv` and `.../b/data.csv` both become `#file-data-csv`. RecordSet ids collide the same way.
- Code: `fairscape_models/conversion/mapping/utils.py:5-9` keeps only `split('/')[-1]`.

### D14. FileObject loses `contentUrl`, checksums, size and format, so every example fails mlcroissant validation. Severity: invalid Croissant
- Repro: `S/scripts/croissant_probe.py` blocks 7 to 9, then `S/venv-mlc/bin/python -I S/scripts/mlc_validate.py out/cr_*.json`.
- Observed:
  - Files that only have `localPath` (frictionless, galaxy-public, mlflow, linked crates) get no `contentUrl`, which is mandatory.
  - `contentSize` and `digest` are never mapped.
  - An empty md5 becomes the literal `"PLACEHOLDERMD5"`.
  - `vcf`, `bam`, `fastq.gz`, `csv.gz` and `h5` all become `text/plain`, and `tsv` becomes `text/tsv`.
- Code: `fairscape_models/conversion/mapping/croissant.py:68-99,327-336`, and `mapping/utils.py:59-62` (`format_md5`).

Checked and fine:
- AI-READI import → export round trip, with 9 of 9 external resources.
- d4d export of all 21 example crates.
- Croissant export of the 22 example crates that don't come from d4d (no exceptions).
- Unicode and YAML dates.
- Nested and `separator` fields becoming `subField` / `repeated`.
## Snakemake import and Cromwell import

Repro files live in `bughunt/wf/`, written S below. These runs are new: Cromwell 92 and snakemake 9.26.1 (from the `snakemake-fairscape` env). CW1–CW4 all reproduce with one script, `cd S && /home/oj/anaconda3/envs/fairscape/bin/python tools/repro_cromwell.py`, which reads `cw/run1/metadata.json` and `cw/run2/metadata1.json`. The WDL for each run sits beside its metadata.

### CW1. A scattered subworkflow keeps only one shard of an inner call that has no File outputs — wrong-provenance
- **Repro:** `S/cw/run1/main.wdl` and `sub.wdl` scatter `call s.subwf as sw` over 3 shards. `subwf.count_lines` outputs only an `Int`.
- **Observed:** the records hold 3 `count_lines` jobs, but the crate has 1 Computation (repro line `[1]`). Shards 1 and 2 vanish silently, so the reads of `part_1.txt` and `part_2.txt` are lost. Failed inner calls and nested scatters collide the same way.
- **Code:**
  - `plugins/cromwell/__init__.py:67-71` (`job_ark_source`) hashes only the task, the call's own shard and its output paths. Inner calls all have shard -1.
  - `iter_calls` (`extract.py:60-80`) drops the parent shard index.
  - The engine's first-writer-wins dedup then discards the duplicates.

### CW2. Two glob outputs with long names that contain a UUID merge into one Dataset — wrong-provenance
- **Repro:** `S/cw/run2/main.wdl`, task `uuid_long`, writes `aligned_reads_for_sample_cohort_batch_0001_<uuid>.txt` twice.
- **Observed:** the 2 files become 1 Dataset. `generated` lists the same `@id` twice, and the second file is lost (repro line `[4]`).
- **Code:**
  - `plugins/cromwell/extract.py:183-185` (`ark_source`) replaces UUIDs under the workflow root with `-`, so both files hash to the same source.
  - `core/arks.py` `slugify(max_len=40)` cuts the name before the UUID.
  - In `cw/run1`, short names already share the hash `0a1126d` and stay distinct only through their slugs.

### CW3. An empty or directory-valued String input becomes a nameless input Dataset — mistranslation
- **Repro:** `S/cw/run1`, task `split`, with `String prefix = ""`.
- **Observed:** a Dataset with `name: ""` is listed in `usedDataset`, and `parameter` is empty (repro line `[2]`). Any String naming an existing directory, such as `"."`, is affected the same way.
- **Code:** `plugins/cromwell/extract.py:166-171` (`is_file`). `resolve("")` returns the metadata directory, which exists.

### CW4. Task Software is keyed on the call alias or subworkflow call name, not the task — mistranslation
- **Repro:** `S/cw/run1`, with `call concat as concat_upper` / `as concat_tagged`, plus the subworkflow tasks.
- **Observed:**
  - The single task `concat` becomes two Software entities, `concat_tagged` and `concat_upper`.
  - Both carry the fallback description instead of the task source.
  - Subworkflow tasks keep the `subwf.` prefix, and their inner shards are all named `subwf.tag`.
- **Code:** `plugins/cromwell/extract.py:60-63` strips only `workflowName + "."`, and for a subworkflow that is the alias `sw`. Aliases are never mapped back to task names, so `task_source()` (`extract.py:83`) finds nothing.

### SM1. Checkpoint jobs are missing, so files from a checkpoint's directory look like raw workflow inputs — wrong-provenance (caused by the reporter, not this repo)
- **Repro:** `S/sm/run1/Snakefile`:
  - `checkpoint scatter` writes `directory("results/chunks")`.
  - `proc_chunk` reads `results/chunks/c{i}.txt`.
  - Run `snakemake -c2`, then `--reporter fairscape`. The outputs are `records.json` and `conv.json`.
- **Observed:** no `scatter` job or Software exists. `results/chunks/c0.txt` and `c1.txt` have `generatedBy: []` and sit in the run's `usedDataset` as source data.
- **Code:** `snakemake-report-plugin-fairscape/.../__init__.py`, in `render`. It builds jobs from `dag.jobs`, and that list leaves out the finished checkpoint. A plain `directory()` rule works (`S/sm/run2`).

### CW5. The CLI cannot run cromwell import — minor
- **Repro:** `python -m fairscape_conversion.core.cli convert cromwell import examples/public-runs/cromwell/encode-mirna-seq.metadata.json out.json`
- **Observed:** a raw `KeyError: 'settings'`. As a result, `--link-crate` can't be used with cromwell from the CLI. The core hunt saw the same failure.
- **Code:** `core/cli.py:36` / `:68`. `cromwell` is not in `PATH_SOURCE_IMPORTS`.

### Observed, not counted as bugs
- **Call-cache hits are not marked.** Their outputs sit under `cacheCopy/`, so a cached rerun gets different ARKs from the original run. That contradicts the plugin docstring's claim that "re-runs reproduce identifiers" (`S/cw/run2/metadata2.json`).
- **Snakemake `params` lose their names.** `tag="v1"` becomes `"'v1'"`; this comes from snakemake's persistence metadata.
- **`run:` jobs have no `command`.**

### Checked and fine
- Every run validates, with no duplicate or dangling ids. That covers all 3 public cromwell runs and the new runs.
- Cromwell:
  - Scatter shards with the same basename stay distinct.
  - Retries keep the last attempt.
  - Failed calls are noted, and optional null outputs are handled.
  - Relative inputs resolve, and subworkflow lineage across a scatter is correct.
- Snakemake: these all come through correctly:
  - wildcards
  - `temp()` and `directory()` outputs
  - `script:` rules and rules with no inputs
  - same basenames in different directories
  - configfiles
- **Not tested:** cromwell and snakemake with `--link-crate` end to end.
## Galaxy (import), WRROC (import / export), CPM / PROV (import / export)

All repro scripts are in `bughunt/prov/repro/` (R below). Run each one as `cd R && /home/oj/anaconda3/envs/fairscape/bin/python -I <script>`. The `prov` package is installed in `R/../venv`.

Real inputs are in `R/../dl`:
- the ResearchObject/workflow-run-crate repo, all of it: profile examples 0.5, 0.6 and 0.7-DRAFT, plus the cwltool, streamflow, type-zoo, autosubmit, COMPSs, WfExS and sparql crates
- from Zenodo: sapporo, pfhub, and three Galaxy invocation exports
- all 127 IWC `.ga` files

Batch drivers: `R/../run_all_wrroc.py`, `check_graph.py`, `cpm_roundtrip.py`, `run_galaxy.py` and `galaxy_check.py`.

### W1. WRROC import fails when `license` is an entity reference or a list — breaking
- **Repro:** `bug_w1_license_ref.py`
- **Observed:** `ValidationError license: Input should be a valid string` for `license: {"@id": ...}` and for a list. This hits:
  - every official profile example1/example2: process and workflow, versions 0.5, 0.6 and 0.7
  - all 6 WfExS crates
  - the pfhub crate
- **Code:** `plugins/wrroc/hooks.py:240`. The export at line 334 passes the value through the same way.

### W2. List-valued `File.encodingFormat` breaks WRROC import — breaking
- **Repro:** `bug_w2_format_list.py`. The real case is the COMPSs crate.
- **Observed:** a ValidationError on `format` for `[mime, {"@id": PRONOM}]`, which is the form RO-Crate recommends.
- **Code:** `plugins/wrroc/parsers.py:182-184` (`_synth_format_file`).

### W3. A SoftwareApplication or ComputationalWorkflow with no `name` breaks WRROC import — breaking
- **Repro:** `bug_w3_software_noname.py`. The real cases are the sparql crates; for example, `scripts/classify_tumor.py` has no name.
- **Observed:** `name: Field required`. RO-Crate only says name SHOULD be present. Files already fall back to the basename via `synth_name`; software gets no such fallback.
- **Code:** `plugins/wrroc/properties.csv` rows 17 and 21.

### W4. Exported PropertyValue `@id`s collide, so a run gets another run's parameter value — wrong-provenance
- **Repro:** `bug_w4_pv_id_collision.py`
- **Observed:**
  - Two runs with `threshold` = 0.5 and 0.9 both export `#pv-threshold-f-workf`.
  - The real cwltool and streamflow ml-predict-pipeline crates export `#pv-label-f-workf` 3 times, `#pv-level-f-workf` 3 times and `#pv-filter-f-workf` twice.
- **Code:** `plugins/wrroc/hooks.py:308` builds the id from `slugify(node['@id'])[-7:]`. `slugify` truncates to 40 characters, so the last 7 characters come from the shared ARK prefix instead of the hash.

### W5. Nested PropertyValues (record-valued) become dangling `usedDataset` refs — wrong-provenance
- **Repro:** `bug_w5_nested_pv.py`. The real case is `draft/type-zoo-run-1-crate`.
- **Observed:**
  - Inner ids such as `#pv-rec/A` are written into `usedDataset` but no node with that id exists.
  - The parameter itself is lost.
  - The export then puts the dangling ids into `object`.
- **Code:** `plugins/wrroc/parsers.py:91-94` (`_object_split`).

### W6. EVI → WRROC export drops `Computation.parameter` and the step nesting — mistranslation
- **Repro:** `bug_w6_export_drops.py R/../out/galaxy_Galaxy-Invocation-of-collectionworkflow.crate.zip.evi.json`
- **Observed:**
  - The `parameter` strings (e.g. `num_lines_param=2`) are lost. They are written by the galaxy, cpm and wrroc imports.
  - `isPartOf` is dropped, so the workflow CreateAction and the step CreateActions come out as flat peers.
  - No ControlAction or OrganizeAction is emitted.
  - The workflow is exported as SoftwareApplication, and there is no `mainEntity`.
- **Code:** `plugins/wrroc/properties.csv` (`drop_export` on `parameter` and `isPartOf`), and `export_convert` in `hooks.py:300-340`.

### CPM1. CPM import turns PROV timestamps into phantom entities and ignores activity times and associations — wrong-provenance
- **Repro:** `bug_c1_times_as_entities.py` (both inputs were written by the `prov` package).
- **Observed:**
  - The time in `used(a, e, 2024-05-01T10:00:00)` becomes a Dataset named "00".
  - The activity's start and end times are ignored; `dateCreated` is the bundle date.
  - A `prov:Person` agent becomes an Organization.
  - `runBy` is the bundle sender instead of the `wasAssociatedWith` agent.
  - `wasInformedBy` and `actedOnBehalfOf` are silently dropped.
- **Code:**
  - `plugins/cpm/hooks.py:223-228` (the stub loop runs over every arg)
  - `_merge_element`
  - `plugins/cpm/parsers.py:62` and `:70`
  - `plugins/cpm/entities.csv` row 6

### CPM2. CPM export uses an undeclared `dct` prefix, so the PROV is invalid — breaking
- **Repro:** `bug_c2_c3_invalid_prov.py ex3.evi.json ex3.prov.json && R/../venv/bin/python -I prov_read.py ex3.prov.json`
- **Observed:** `Invalid Qualified Name: dct:hasPart`. 7 of the 12 WRROC-derived crates fail this way.
- **Code:** `plugins/cpm/hooks.py:561` emits `dct:hasPart`, but only the `cpm` prefix is declared (line 531).

### CPM3. CPM export writes absolute-URL identifiers verbatim as qualified names — breaking
- **Repro:** `bug_c2_c3_invalid_prov.py sparql_prc.evi.json sparql.prov.json`, then `prov_read.py sparql.prov.json`
- **Observed:** the output contains `entity(https://www.imagemagick.org/, ...)`, and `prov` fails with "An identifier is missing". ORCID and `doi:` identifiers break the same way.
- **Code:** `plugins/cpm/hooks.py:60` (`_QN_RE` matches `https:`) and `_export_qn` at line 442.

### CPM4. CPM export loses agents and timestamps — mistranslation
- **Repro:** `bug_c4_export_loses_agents_times.py ex3.evi.json`
- **Observed:**
  - Every activity is written as `activity(qn, -, -, ...)`; `dateCreated` is not exported.
  - `runBy` never becomes `wasAssociatedWith`.
  - Persons and organizations are exported only if they have a `cpm:` additionalType or a `prov:` relation.
- **Code:** `plugins/cpm/hooks.py:562` and lines 497-520.

### CPM5. Software round-trips through CPM as a Dataset — minor
- **Repro:** `bug_c5_software_roundtrip.py ex3.evi.json`
- **Observed:** `usedSoftware` comes back as `usedDataset`, because the export writes no type marker that would identify it as software.

### G1. Galaxy import silently writes an invalid crate (no `runBy`) when no author is given — breaking
- **Repro:** `bug_g1_runby.sh`, run on the shipped `examples/public-runs/galaxy/FeS2-Analysis.rocrate.zip`.
- **Observed:** the CLI exits 0, but `ROCrateV1_2` rejects the crate with `runBy Field required`. The same happens for N2O-Figs6 and the Zenodo exports. Galaxy exports carry no user, and unlike wrroc this importer has no "Unknown" fallback.
- **Code:** `plugins/galaxy/parsers.py:86-87` (`crate_author` returns None), and `plugins/galaxy/properties.csv` rows 4 and 15.

### Checked and fine
- WRROC import of revsort, streamflow, cwltool, sapporo, autosubmit, snakemake and Galaxy-WRROC crates. Correct:
  - object/result direction
  - `isPartOf` on tool runs
  - start and end times
  - distinct same-name files
  - wrroc → EVI → wrroc restores the `@id`s
- Galaxy import of 5 real invocations: the job graph matches the `.ga` step graph, with no dangling or duplicate ids. All 127 IWC `.ga` files import and validate.
- The shipped CPM reference crate round-trips through PROV-JSON and PROV-N with no lost edges.
- CPM import keeps PROV relation directions correct, and keeps same-named locals under different prefixes distinct.
## Frictionless (import / export), C2M2 (import), REDCap (import)

Scripts and inputs live in `bughunt/fric-c2m2-redcap/` (S below). Run everything from `S/out` with `PY` = `/home/oj/anaconda3/envs/fairscape/bin/python`.

Real inputs used:
- **Frictionless:** `frictionlessdata/example-data-packages` (`S/dl/edp`), plus the datahub packages gdp, co2-ppm, finance-vix, population and country-codes.
- **C2M2:** the HMP Basic_relational submission from `nih-cfde/c2m2` (`S/inputs/hmp_basic`) and the cfde-deriva master `C2M2_datapackage.json`.
- **REDCap:** about 30 REDCapR test projects, and the redcapAPI TestRedcapAPI dictionary and records.

Hand-built inputs:
- `S/inputs/fpkg1`, which passes `frictionless.validate`.
- `S/inputs/c2m2_multi`, which uses only master-datapackage tables and columns.

### F1. A resource `schema` or `dialect` given as a path or URL crashes the import — breaking
- **Repro:**
  - `PY -m fairscape_conversion.core.cli convert frictionless import ../inputs/fpkg1 x.json`
  - The real package `../dl/edp/donation-codes-via-url` fails the same way.
  - For the dialect case, run `PY ../scripts/fric_misc.py ..`.
- **Observed:** `AttributeError: 'str' object has no attribute 'get'`. The spec allows a string reference here.
- **Code:** `plugins/frictionless/__init__.py:89`, `parsers.py:105`, `parsers.py:216` and `parsers.py:225`.

### F2. Multipart resources (`path` given as a list) keep only the first part — mistranslation
- **Repro:** `convert frictionless import ../inputs/fpkg2 fpkg2.crate.json`, then look at resource `payments`.
- **Observed:** only `data/part1.csv` is kept, and `contentSize` covers part 1 only. `part2.csv` is gone, and the export writes a single path.
- **Code:** `plugins/frictionless/extract.py:68-72` (`_first_path`) and `:89`.

### F3. Inline `data` resources lose their data, and the export is invalid — mistranslation
- **Repro:** the same `fpkg2` run, resource `codes`. Then `convert frictionless export` and validate the result.
- **Observed:** no `properties.csv` rule maps `data`. The exported resource has neither `path` nor `data`, so frictionless reports `resource-error: one of the properties "path" or "data" is required`.
- **Code:** `extract.py:92-104` and `properties.csv`.

### F4. A sha256 or sha1 `hash` is stored in `md5` — mistranslation
- **Repro:** `fpkg2`, resource `people`, which has `"hash": "sha256:244f…"`.
- **Observed:** the output has `"md5": "244f1c82…"` plus `hashAlgorithm: sha256`. It should use the `sha256` property instead.
- **Code:** the `resource,hash,Dataset,md5` row in `properties.csv`, and `parsers.py:156-162`.

### F5. A data file missing from disk means the resource loses its path entirely — mistranslation
- **Repro:** `PY ../scripts/fric_misc.py ..` (output line F, input `S/dl/gdp`). co2-ppm, finance-vix and population show the same thing.
- **Observed:** `localPath` and `contentUrl` are both None. The export writes `path: None`, which fails validation.
- **Code:** `extract.py:95-101`. The relative-path fallback in the `elif` branch only runs when `base_dir` is None.

### F6. A package with no `contributors` produces an invalid crate — breaking with `validate=True`
- **Repro:** `PY ../scripts/fric_misc.py ..` (output line G, `edp/periodic-table`). About 20 of the 27 example packages fail, as do gdp, co2-ppm and population.
- **Observed:** `ROCrateV1_2: author Field required` on every resource, Schema and descriptor. The root `author` is `""`.
- **Code:** `package_author` in `parsers.py` returns None. See also `properties.csv:5,32`.

### F7. Every frictionless export writes an invalid `created` value — mistranslation
- **Repro:** `PY ../scripts/fric_roundtrip.py . ../dl/edp/cpi`. The same happens for any other package.
- **Observed:** the export fails with `package-error: property "created" is not valid "datetime"`. Import truncates `2024-05-06T07:08:09Z` to `2024-05-06`.
- **Code:** `plugins/frictionless/__init__.py:252`, and `created[:10]` in `extract.py`.

### F8. c2m2 import writes table `contentUrl` as `file:///file.tsv`, the filesystem root — minor
- **Repro:** run c2m2 import, then frictionless export (`fric_misc.py`, last two output lines). The export carries `path: "file:///file.tsv"`.
- **Code:** `plugins/c2m2/mapper.py:250` and `:285`.

### C2M2-1. `file_describes_biosample`, `file_describes_subject` and `file_describes_collection` are never mapped — mistranslation
- **Repro:** copy `plugins/c2m2/input-datapackage` to `S/inputs/c2m2_fixture`, then run `c2m2.convert('import','../inputs/c2m2_fixture',output_path='fixture_crate')`.
- **Observed:** the `sample.tsv` file node and Sample `bio1` never reference each other. In the HMP subset, all 80 `file_describes_biosample` rows are lost.
- **Code:** `plugins/c2m2/associations.csv` has no `file_describes_*` rows.

### C2M2-2. Projects and `project_in_project` are dropped — mistranslation
- **Repro:** `PY ../scripts/c2m2_check.py ../inputs/c2m2_multi c2m2_multi_crate` prints `project nodes: []`.
- **Observed:** the only trace of a project is a `project_local_id` PropertyValue on biosamples, without its namespace.
- **Code:** `entities.csv` and `associations.csv` have no project rows. `mapper.py:_resolve_metadata` reads only the first project row, for the crate name.

### C2M2-3. Entities with the same `local_id` in different `id_namespace`s collapse into one node — mistranslation, mislinked edges
- **Repro:** the same `c2m2_check.py` run. Two namespaces each contain subject s1, biosample b1 and file f1.
- **Observed:** only namespace A's nodes survive. Namespace B's brain biosample, its 50-year-old subject and `brain.fastq` are dropped. Every association row from namespace B resolves to namespace A's node.
- **Code:** the id templates in `entities.csv:2-5` (`{prefix}-subject/{local_id}`) omit `id_namespace`. The duplicate is then removed by the first-wins dedup at `impl.py:475-480`.

### C2M2-4. The conversion Computation claims to have generated the DCC's source data files — wrong-provenance
- **Repro:** `c2m2.convert('import','../inputs/hmp_basic',output_path='hmp_basic_crate')`, then look at the Computation's `generated` list.
- **Observed:**
  - `generated` lists all 40 file-row entities, e.g. the sequencing archive `SRR048068.tar.bz2`.
  - Those file nodes have `generatedBy: []`, so the inverse link is inconsistent.
  - `usedDataset` lists only `datapackage.json`, not the TSVs it read.
- **Code:** `entities.csv:2` (`file` level=`generated`), `impl.py:93-94` and `:482-483`, and `mapper.py:329`.

### R1. `time_hh_mm_ss` and `time_mm_ss` get an HH:MM pattern — mistranslation
- **Repro:** `PY ../scripts/redcap_repro.py ../inputs/rc1`.
- **Observed:** `13:45:30` fails the generated `^[0-9]{2}:[0-9]{2}$` pattern.
- **Code:** `redcap/parsers.py:71` folds every `time*` validation into one family. See also `field_types.csv:14`.

### R2. `number_comma_decimal` and `number_Ndp_comma_decimal` become JSON `number` — mistranslation
- **Repro:** the same script. Also `PY ../scripts/redcap_data_validate.py rc ../inputs/rapi` on real records.
- **Observed:** comma-decimal values like `36,5` raise type-errors.
- **Code:** `parsers.py:67` and `field_types.csv:10`.

### R3. REDCap's soft min/max and per-event "required" become hard constraints — mistranslation
- **Repro:** `PY ../scripts/redcap_data_validate.py rc ../dl/redcapr/inst/test-data/projects/*/`
- **Observed:**
  - Min/max: real exports fail on out-of-range values, e.g. `height=7` against min 130.
  - Required: longitudinal and repeating exports leave cells blank on other events, so `longitudinal-with-repeating-instrument` gets 262 errors and `vignette-repeating` gets 15.
- **Code:** min/max at `parsers.py:186-190`; required at `parsers.py:182` and `:307`.

### R4. With `labels=True`, yesno, truefalse, checkbox and `_complete` columns keep their raw-code types — mistranslation
- **Repro:** `redcap_repro.py`, second block.
- **Observed:** the types stay `boolean` or `integer` with enums `[0,1]` / `[0,1,2]`, so label values like `Yes`, `Checked` and `Complete` fail validation. Only radio and dropdown handle labels.
- **Code:** `field_columns` and `form_status_column` in `parsers.py`; see also `field_types.csv:2-4`.

### R5. Survey `<form>_timestamp` columns are typed as undocumented strings — minor
- **Repro:** `PY ../scripts/redcap_all.py ../dl/redcapr/inst/test-data/projects/survey/`
- **Observed:** `fieldType: undocumented`, a plain string with no datetime pattern.
- **Code:** `EXPORT_BOOKKEEPING` in `parsers.py` has no entry for `_timestamp`.

### Checked and fine
- **Frictionless:**
  - These round-trip correctly: primaryKey, foreignKeys, missingValues, enum, min/max length, pattern, year/date types and remote URLs.
  - fpkg2 crates validate, YAML descriptors import, and there are no duplicate `@id`s.
- **C2M2:** these link correctly within a single namespace:
  - `biosample_from_subject`
  - `collection_in_collection`
  - `biosample_in_collection`
  - `subject_disease`
- **REDCap:**
  - Input handling: BOM and Unicode, checkbox expansion, `_complete` columns, and longitudinal and repeating bookkeeping columns.
  - De-identified header filtering and the API-format `metadata.csv`.
  - All REDCapR dictionaries pass `validate=True`.
## MLflow import and Python `track`

Scripts are in `bughunt/mlflow_python/` (referred to as S below). Helpers:
- `S/py1/check.py` and `S/mlf/show.py` print each run's inputs and outputs.
- `S/validate.py` checks for duplicate or dangling ids and validates against ROCrateV1_2.
- `P` = `/home/oj/anaconda3/envs/fairscape/bin/python`.

### P1. track links to the stale version of a file that a later run overwrote (wrong provenance)
- **Repro:** `S/py1/`. Start with `data.csv` in `work/crate` and track three runs with `--crate-dir .`: read_data, then rewrite_data, then read_data again.
- **Observed:** the third run's `usedDataset` is `dataset-data-csv-97fd11a`, the original external input, which has no `generatedBy`. The rewrite run's output `dataset-data-csv-0e9f508` is not used.
- **Expected:** the third run uses the latest version, the rewrite run's output.
- **Code:** `plugins/python/track.py:84-88` (`merge()`). The `if nid in known: continue` check runs before the by-path match. Input ARKs hash only the path, so the fragment's input id equals the old node's id, and its references are never rewritten to the latest node.

### P2. A relative `--crate-dir` is resolved after the script runs, so a script that calls `os.chdir` writes the crate to the wrong place (breaking)
- **Repro:** `S/py2/chdir_script.py`. From `ws/proj`, run `P -m fairscape_conversion.core.cli track ../../chdir_script.py --crate-dir ../crate`.
- **Observed:** the crate is written to `ws/proj/crate/` instead of `ws/crate`. The CLI still reports `../crate`, and the cwd is not restored.
- **Code:** `plugins/python/track.py:149` resolves the path inside `add_run`, which runs after `runpy`. `track_script` (`track.py:189-212`) never resolves it up front.

### P3. A relative `--input FILE` is resolved against the crate dir instead of the cwd, then silently dropped (wrong provenance)
- **Repro:** `S/py3/sub.py`. From `ws`, run `P -m fairscape_conversion.core.cli track ../sub.py --crate-dir crate --input raw.csv -- raw.csv crate/copy.csv`.
- **Observed:** the run reports "0 in", and `raw.csv` is not recorded. There is no warning.
- **Code:** `plugins/python/track.py:150-151` builds `crate_dir / p`, then the `os.path.isfile` filter in `record.py` `build_record` drops the file.

### P4. `np.savez` / `np.savez_compressed` to a path without `.npz` loses the output, and reading it back is recorded as an external input (wrong provenance)
- **Repro:** `S/py6/savez.py`. From `ws`, run `P -m fairscape_conversion.core.cli track ../savez.py --crate-dir crate`.
- **Observed:** `no_ext.npz` is never recorded. `no_ext2.npz` is written and read back in the same run, yet appears as a `usedDataset` with no `generatedBy`.
- **Code:** `plugins/python/record.py:147-159` (`_patch_path_arg`) records the path as given (`crate/no_ext`), but numpy appends `.npz`. The real write goes through zipfile/`io.open`, which bypasses the patched `builtins.open`.

### P5. The script's Software node is merged by path into whatever node already sits at that path (wrong `usedSoftware`)
- **(a) Edited script** (`S/py7/`): track `step.py`, edit it, then track it again. Both Computations end up with `usedSoftware` = `software-step-b09da88`, the ARK of the old code. No Software node is created for the new code, and the old node's `contentUrl` now holds the new code.
- **(b) Generated script** (`S/py8/`): `writer.py` writes `crate/gen.py`, then run `track crate/gen.py --crate-dir crate`. gen's `usedSoftware` points at `dataset-gen-py-c3927a5`, an EVI Dataset with `generatedBy` = the writer run. No Software node exists for gen.
- **Code:** `plugins/python/track.py:86-91`. Every node without `generatedBy` goes through the path-reuse lookup, including the Software node.

### M1. mlflow: a dataset input is aliased to an artifact that a later run logged (time-inverted provenance)
- **Repro:** `S/mlf/gen_store2.py`, then `P S/mlf/convert.py sqlite:///S/mlf/sq2/mlflow.db out_sq2 '{"experiment":"gamma"}'`.
  - Run "consumer" logs `from_pandas(source=x.csv)`.
  - A later run, "exporter", calls `log_artifact(x.csv)`.
- **Observed:** consumer's `usedDataset` is `dataset-x-csv-7b66912`, whose `generatedBy` is the exporter. The exporter started after the consumer ended.
- **Code:** `plugins/mlflow/extract.py:222-258` (`_alias_dataset_inputs`) matches on basename and size only, with no check on time or run order.

### M2. mlflow: two logged models with the same name in one run share a directory, so one overwrites the other (wrong provenance / data loss)
- **Repro:** same store as M1. The run "two-models" logs a LogisticRegression and a DecisionTree, both with `name="model"`.
- **Observed:** both MLModel nodes have `contentUrl` `two-models-db574f7c/model/`. That directory holds only the second model's files.
- **Code:** `plugins/mlflow/extract.py:518-521` uses `run_dir/<model name>` as the download destination, which is not unique per model_id.

### M3. mlflow: a run-artifact folder that shares a logged model's name pulls the model's internal files in as separate artifacts (mistranslation)
- **Repro:** same store as M1. The run logs a model named "model" and also calls `log_text(..., "model/notes.txt")`.
- **Observed:** the run's `generated` list includes the model's internal files as plain Datasets: MLmodel, conda.yaml, model.skops, python_env.yaml and requirements.txt.
- **Code:** `plugins/mlflow/extract.py:102-107` and `467-476`. In MLflow 3, `list_artifacts(path)` also returns the logged model's files, and nothing filters them out.

### M4. mlflow: `usedMLModel` is silently dropped when the model's producing run is outside a `run_id` export (lost edge)
- **Repro:** `S/mlf/gen_store.py`, then `P S/mlf/convert.py sqlite:///S/mlf/sq/mlflow.db out_sq_eval '{"run_id":"<evaluate id from sq/work/ids.json>"}'`.
- **Observed:** the "evaluate" Computation has no `usedMLModel`, while the full-experiment export has it. Out-of-scope dataset inputs, by contrast, are kept as nodes with no producer.
- **Code:** `plugins/mlflow/extract.py:494` builds models only for runs in scope, and `plugins/mlflow/parsers.py:99-103` (`run_used_models`) drops ids that are not in `guid_map`.

### Checked and fine
- **mlflow, file store and sqlite:**
  - Runs: nested and grandchild runs get the correct `isPartOf`, and FAILED status is recorded.
  - Params (including special characters) and metrics land on the correct run.
  - Inputs: pandas, numpy and autolog datasets; colspec schemas; models used as inputs and as `trainedOn`.
  - Also fine: artifacts in subdirectories, the linked-crate stub, and ROCrateV1_2 validation.
- **track:**
  - Reads after writes; double writes.
  - Captured writers: pathlib, pandas, np.save, savefig, shutil and parquet.
  - Files outside the crate.
  - A failing script records nothing, by design.
  - `%%fairscape` magic.
- **Not covered:** MLflow 2.x stores. Registered model versions are not mapped at all.
