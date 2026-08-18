# Migration & rollout

`fairscape_conversion/` is a parity-proven reimplementation of the four converters under one
mapping format **and one engine**: wrroc, d4d, and c2m2 imports all run through
the shared `run_pipeline` driver (`core/engine.py`); exports (wrroc export, d4d
reverse) are bespoke drivers composing the same kernel pieces. Nothing in
production has been changed yet. This is the plan to switch over, in the order
of lowest to highest risk.

## Current state

| converter | original location | status in `fairscape_conversion/` | direction |
|---|---|---|---|
| WRROC ↔ EVI | `workflow_run_crate/wrroc` (development tree) | self-contained, on `run_pipeline`, byte-parity | both |
| D4D ↔ RO-Crate | `bridge/convertV2` (development tree) | self-contained, on `run_pipeline`, byte-parity | both |
| C2M2 → RO-Crate | `b2ai-metadata-generation/0.1-alpha/c2m2-rocrate/src` | self-contained, on `run_pipeline`, byte-parity | import |
| RO-Crate → Croissant | `fairscape_models/fairscape_models/conversion` | output-parity (drives the untouched production converter) | export |

wrroc, d4d, and c2m2 have **no runtime dependency** on their original
locations — the originals stay untouched purely as parity-test references.
Croissant is the remaining production-coupled step: its plugin still drives the
`fairscape_models` converter with a CSV-reconstructed configuration.

Where a workflow's per-record mapping is genuinely bespoke (c2m2's vars/computed
tokens + association attach, d4d's many-to-one merge) the plugin overrides the
pipeline's `map_record` hook; everything else (record iteration, first-wins
dedup, id resolution, rule selection) is the shared kernel.

## Rollout order

### 1. wrroc and d4d (research code — safe now)
These live in the development tree and have no production importers. To adopt:
- Point any caller at `fairscape_conversion.plugins.wrroc.convert` / `fairscape_conversion.plugins.d4d.convert`.
- The old dirs (`workflow_run_crate/wrroc`, `bridge/convertV2`) stay in place as
  the parity-test references; they are not imported by `fairscape_conversion/` at runtime.

### 2. c2m2 (standalone prototype — done, adopt at will)
`fairscape_conversion.plugins.c2m2` is fully self-contained: the engine machinery was ported
into the plugin (`mapper.py` / `parsers.py` / `ontology.py`) and runs on the
shared pipeline; the unified CSVs are the authoritative mapping (edit them
directly — the loader validates parser names at import). `cv_bases.csv` drives
the ontology base tables. `root.json` (crate identity/root config) is
structural, not row-mapping data, and stays as a small JSON in the plugin.
The old `c2m2-rocrate/src` (including its JSON mappings) is untouched and used
only by the parity tests; point callers at
`fairscape_conversion.plugins.c2m2.convert("import", datapackage_dir)`.

### 3. croissant / fairscape_models (production — do last, carefully)
`fairscape_models/conversion` is imported by three production consumers. **Do not
change them until this plugin has soaked.** The exact import sites to switch at
rollout:

| consumer | file | what it imports |
|---|---|---|
| fairscape-cli | `src/fairscape_cli/commands/build_commands.py` | `ROCToTargetConverter`, `MAPPING_CONFIGURATION` (Croissant export) |
| fairscape-cli | `src/fairscape_cli/datasheet_builder/rocrate/datasheet_generator.py` | the FairscapeDatasheet mapping configs |
| fairscape-mds | `src/fairscape_mds/routers/rocrate.py` | Croissant export in the API |
| fairscape-mds | `src/fairscape_mds/crud/llm_assist.py` | `TargetToROCrateConverter` + `d4d_to_rocrate` (D4D import) |

Switch path for Croissant: replace the direct
`ROCToTargetConverter(source, MAPPING_CONFIGURATION)` call with
`fairscape_conversion.plugins.croissant.convert("export", crate_dict)` (it builds the same
configuration from the CSVs and runs the same converter). The D4D import path in
`llm_assist.py` is superseded by `fairscape_conversion.plugins.d4d.convert("import", ...)`.

### Not migrated (by design)
`fairscape_models/conversion` also produces **FairscapeDatasheet** (HTML sections)
and **AI-Ready scores** (v1/v2). These are dominated by imperative graph-walking
and rubric scoring, **not** property mappings — forcing them into `properties.csv`
would be abstraction for its own sake. They keep their current code. If they ever
want the shared engine, they can register their builders as `hooks` and consume
the pipeline, but there is no mapping to fairscape_conversion.

## Packaging note
`fairscape_conversion` is an installable package (`pip install -e .`) and imports
`fairscape_models` (as all four converters already do). Before production
adoption, decide whether it stays standalone or whether the relevant plugins are
vendored into `fairscape_models` / `fairscape-cli`. Moving the whole engine into the published
`fairscape_models` package would let it replace the three copy-pasted spec
interpreters in `conversion/converter.py` and `conversion/d4d_converter.py` — the
natural end state, and the reason croissant was ported as the proof it fits.
