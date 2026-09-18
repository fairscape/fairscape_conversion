# How fairscape-conversion works

*(User-facing instructions are in the top-level `README.md`; this is the
design.)*

Four converters used to translate between fairscape RO-Crates and other
serializations, each in its own mapping format:

| was | format you had to learn |
|---|---|
| `bridge/convertV2` (D4D ↔ RO-Crate) | 1 CSV, 12 bespoke columns, asymmetric parsers |
| `workflow_run_crate/wrroc` (WRROC ↔ EVI) | 2 CSVs, its own columns |
| `c2m2-rocrate` (C2M2 → RO-Crate) | per-table JSON mappings + manifest |
| `fairscape_models/conversion` (→ Croissant / D4D / …) | Python dicts, 3 copied interpreters |

**Now they all speak one format — and one engine.** A converter is a *plugin*:
a folder of CSVs (`entities.csv` + `properties.csv`, sometimes
`associations.csv` / `cv_bases.csv`) plus one subclass of
`core.plugin.PluginBase` holding its named parsers and step methods. The CSV
columns are identical across plugins — read `MAPPING-SCHEMA.md` once and you can
read any converter. Every import (wrroc, d4d, c2m2) runs through the shared
`run_pipeline` driver in `core/engine.py`: the plugin's `pre` (by default just
its `load_source` + `classify`) parses the source into records, the engine maps
each record (a plugin overrides `map_record` where its mapping is genuinely
bespoke), `link` adds cross-node edges, `assemble` builds the final object.
Workflow-specific algorithms (a join, a linking pass, ARK minting) stay as
named parsers or methods on the plugin class; they never become a new format or
a new engine.

> Rule of thumb: **if it is data it lives in a CSV; if it is an algorithm it is a
> named parser or hook.**

One pass runs *after* every import, outside the plugin: **linking**
(`core/linking.py`). Given `linked_crates=[…]` it reads the finished crate,
finds the producer-less entities, and for each one asks the linked crates
(by path, then md5, then containing directory) whether they already describe
that file; a hit replaces the node with a stub under the upstream `@id`,
rewrites every reference, and adds one pointer node per upstream crate
(`ro-crate-metadata`, the release-crate field, on a node the root does not
list in `hasPart`). It is wired in `PluginBase.import_`, so a plugin takes
part by putting a resolvable `contentUrl`/`localPath` on what it consumed and
nothing else. `examples/linked-crates/README.md` has the convention.

## Layout

```
fairscape_conversion/
  MAPPING-SCHEMA.md      the column-by-column spec — read this first
  core/                  the shared engine (loader, kernel, pipeline, PluginBase,
                         records helpers, common parsers, roundtrip, cli)
  plugins/
    example/    entities.csv properties.csv input.json golden.json     (the minimal plugin — copy this to start yours)
    wrroc/      entities.csv properties.csv parsers.py hooks.py        (bidirectional, pipeline)
    d4d/        entities.csv properties.csv parsers.py impl.py         (bidirectional, pipeline import)
    c2m2/       entities.csv properties.csv associations.csv cv_bases.csv constants.csv computed.csv
                impl.py mapper.py parsers.py ontology.py root.json     (import-only, pipeline, self-contained)
    croissant/  entities.csv properties.csv parsers.py impl.py         (export-only, drives the production converter)
    snakemake/  entities.csv properties.csv parsers.py input.json golden.json
                (import-only: Snakemake run records -> EVI crate; the conversion
                 layer of snakemake-report-plugin-fairscape, which owns all
                 Snakemake/filesystem I/O and hands plain data here)
    cromwell/   entities.csv properties.csv parsers.py extract.py input.json golden.json
                (import-only, self-contained like c2m2: Cromwell run metadata
                 JSON -> EVI crate; extract.py owns the metadata/filesystem I/O,
                 so convert() takes either a metadata.json path or plain
                 records. nf/cromwell-fairscape is the parity reference.)
    mlflow/     entities.csv properties.csv parsers.py extract.py input.json golden.json
                (import-only, self-contained: MLflow has no end-of-run hook, so
                 extract.py walks a finished experiment/run through the
                 MlflowClient read API post-hoc; convert() takes a tracking
                 URI / mlruns dir or plain records. Deterministic ARKs keep the
                 MLflow run_id by design. nf/mlflow-fairscape is the harness.)
    galaxy/     entities.csv properties.csv field_types.csv parsers.py extract.py
                input-store/ input.json golden.json
                (import-only, self-contained: Galaxy's invocation export
                 (model store: *_attrs.txt + workflows/*.ga; archive or
                 folder), a bare .ga, or a Galaxy server via the API ->
                 the invocation + every job as Computations, tools /
                 workflow / Galaxy as Software, datasets (history copies
                 collapsed) and collections. field_types.csv maps Galaxy
                 datatypes to MIME types. The wrroc plugin covers Galaxy's
                 RO-Crate flavoured export; this one keeps what it drops.)
    redcap/     entities.csv properties.csv field_types.csv parsers.py extract.py
                input-dictionary.csv input-records.csv input.json golden.json
                (import-only, self-contained: a REDCap data dictionary (CSV
                 download or API metadata JSON) -> a tabular EVI Schema of the
                 record export's columns, plus Datasets for the files and the
                 export Computation. field_types.csv is the REDCap type ->
                 JSON-Schema type table; extract.py owns the file I/O.)
    frictionless/ entities.csv properties.csv field_types.csv parsers.py extract.py
                input-datapackage/ input.json golden.json
                (bidirectional, self-contained: any Frictionless Data Package
                 -> a Dataset per resource + a tabular EVI Schema per Table
                 Schema (constraints, keys, missingValues kept), and any
                 EVI crate -> datapackage.json (export composes
                 apply_export_rules like wrroc). No provenance is invented.
                 c2m2 stays separate: it is one profile with fixed tables
                 and ontology columns.)
  docs/NEW-PLUGIN.md     how to add a plugin, start to finish
  docs/MIGRATION.md      how to roll this out to production
  archive/               inert snapshot of the pre-PluginBase implementation
  tests/                 golden-file + example tests (hermetic), parity tests
                         (need the original converters checked out alongside)
  examples/              one runnable example per conversion, on the plugin
                         fixtures (run_all.py runs them all); examples/mlflow/
                         is the live walk-through — a notebook that trains a
                         model, converts its tracking store, and ships the
                         crate it produced
```

Exports are bespoke `export()` overrides that compose the same kernel pieces
(wrroc export, d4d reverse) — same CSVs, same parser registries, per-workflow
assembly.

`core/arks.py` carries the shared deterministic ARK scheme
(`ark:{naan}/{prefix}-{slug}-{sha1[:7]}`); plugins that tag their ids fold the
tag into the prefix (wrroc).

## The format in one screen

`entities.csv` — one row per source entity class → what target it becomes, how
its `@id` is set. `properties.csv` — one row per source-property → target-property,
naming the parser for each direction. Parsers share one signature
`fn(value, rule, ctx)` and are registered by name. Full column list and one
worked row per plugin: **`MAPPING-SCHEMA.md`**.

Two extra CSVs exist only where a workflow needs them (currently just c2m2):
`associations.csv` (join-table edges) and `cv_bases.csv` (CV → ontology IRIs).

## Is it really the same as before?

Yes, and it is tested. `tests/` runs each plugin against the original standalone
converter on its own fixtures and asserts the output is **byte-for-byte
identical**, both directions:

```
python3 -m pytest tests/ -q      # run from the package directory
```

- wrroc: import + export + round-trip on both example crates.
- d4d: forward + reverse + round-trip on AI_READI / CHORUS / CM4AI / VOICE.
- c2m2: the produced crate matches the standalone converter end-to-end on
  c2m2-mini + 4 DCC datapackages, and cv_bases.csv reproduces the original
  ontology base tables exactly.
- croissant: the reconstructed config drives the production converter to identical
  Croissant JSON on every schema-bearing crate.

The originals stay in the original development tree, untouched (they are the
parity references); nothing in this package imports them at runtime, and the
parity tests skip when they are not checked out alongside. The golden-file and
example tests (`tests/test_plugin_examples.py` and each self-contained
plugin's test file) are hermetic and run everywhere.

## Adding / changing a mapping

Edit the CSV. A new field is a new `properties.csv` row; a new source type is a
new `entities.csv` row. Only a genuinely new *algorithm* (a parser the CSV names
that nobody wrote yet) touches Python — add it to that plugin's `parsers.py` and
the loader will tell you at import time if a CSV names something unregistered.

## Adding a whole new converter

Read **`NEW-PLUGIN.md`** and copy **`plugins/example/`** — the minimal
runnable plugin. The short version: write the two CSVs, subclass `PluginBase`
with a ~2-line `load_source()` (how to read your format) and an `assemble()`
(how to wrap the result), and pin the output with a golden-file test.
