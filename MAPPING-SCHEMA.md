# Unified converter mapping format

One mapping format for every fairscape RO-Crate converter. A converter is a
**plugin**: a folder of CSVs (the mapping data) plus one subclass of
`core.plugin.PluginBase` holding the workflow-specific algorithms (named
parsers + step methods; see `docs/NEW-PLUGIN.md`). The core engine
(`fairscape_conversion/core/`) reads the CSVs and drives the conversion; you never re-read a
bespoke format to understand a converter — you read these CSVs.

Guiding rule: **if it is data it lives in a CSV; if it is an algorithm it is a
named parser or hook.** Blank cells are ignored. List-valued cells are
pipe-joined (`a|b|c`).

Every plugin has `entities.csv` + `properties.csv`. Some plugins add
`associations.csv` and/or `cv_bases.csv` (currently only c2m2 needs them). None
of these files are required to be non-empty — an export-only plugin may leave
half the columns blank.

---

## `entities.csv` — one row per source entity class

How a source node/table/record is recognized and what target entity it becomes.
Row order is match precedence (first matching row wins).

| column | meaning |
|---|---|
| `source_type` | the source `@type` token, C2M2 table name, or model class name to match |
| `discriminator` | named predicate that further gates the match (blank = match any). e.g. wrroc `instrument_is_workflow`; the datasheet/croissant `ROOT` vs `COMPONENT` position |
| `target_type` | the target entity/class produced (empty ⇒ node kept as-is or dropped, see `level`) |
| `target_type_iri` | pipe-joined `@type` array to stamp on the target node, e.g. `prov:Activity\|https://w3id.org/EVI#Computation` |
| `level` | role tag consumed by hooks: `workflow`, `tool`, `data`, `software`, `root`, `component`, `agent`, `drop` |
| `id_strategy` | how the target `@id` is set: `keep` (reuse source id), `mint`, `persistent_or_mint`, `persistent_ark_or_mint`, `ontology_term`, `column` |
| `id_template` | `{token}`-interpolated mint pattern, e.g. `{prefix}-biosample/{local_id}` |
| `id_column` | source column/field carrying the id (for `persistent_*`, `ontology_term`, `column`) |
| `keep_identifier` | `TRUE` ⇒ stash the original source `@id` as `identifier` so a reverse trip can restore it |
| `mint_prefix` | short stem for minted ARKs (wrroc), e.g. `computation-main` |
| `note` | free text |

`level` semantics: `agent` = kept in the output graph unchanged; `drop` = not
emitted as an entity (a hook may still harvest data from it); everything else is
a real target node. The engine mints an `@id` for every non-`agent`/non-`drop`
node per `id_strategy`.

---

## `properties.csv` — one row per source-property → target-property

One row moves one property, in one or both directions.

| column | meaning |
|---|---|
| `source_type` | owning source entity (matches an `entities.source_type`) |
| `source_property` | source field/column read (blank ⇒ constant or synthesized) |
| `target_type` | owning target entity |
| `target_property` | target field written |
| `import_parser` | named parser, source→target direction (blank ⇒ not imported) |
| `export_parser` | named parser, target→source direction (blank ⇒ not exported) |
| `direction` | `both`, `import`, or `export` (which directions this row participates in) |
| `reverse_primary` | `TRUE` ⇒ for a many-to-one target, this source wins on the reverse trip |
| `requirement` | `required`, `recommended`, `optional`, `synthesized`, `passthrough`, `nohome` (documentation + passthrough behaviour) |
| `cardinality` | `scalar` or `list` (target cardinality; `list` accumulates all sources, `scalar` is first-write-wins) |
| `constant_value` | `{token}`-interpolated literal when `source_property` is blank |
| `fallback_source` | second source field tried when the first is empty |
| `fallback_parser` | parser applied to `fallback_source` |
| `source_table` | CV/lookup table this field resolves against (c2m2) |
| `param_name` | name for a wrapped `PropertyValue` when `target_property` is `additionalProperty` (c2m2) |
| `wrap` | wrap the value: `ident_ref`, `property_value`, `ruled_out_pv` (blank = none) |
| `note` | free text |

**`requirement` = `passthrough`** rows are copied verbatim as extra keys and
re-emitted on export (fairscape models allow extra keys). **`nohome`** rows are
documented drops (a target property with no home the other direction).

**Many-to-one merge.** When several `properties.csv` rows share one
`target_type` + `target_property`, they merge: a `list` target accumulates every
source's output, a `scalar` target keeps the first non-empty in row order (put
the `reverse_primary` source first so it wins). This is how d4d collapses
`intended_uses`, `purposes`, `tasks`, … onto `rai_data_use_cases`.

---

## `associations.csv` — join-table edges (c2m2 only)

C2M2 encodes relationships in link tables (`biosample_disease`, …). Each row is
one edge rule. The join algorithm itself (build a guid index, look each node up
by both its natural key and its `@id`) lives in the c2m2 `hooks.py`; this CSV is
only the rule data.

| column | meaning |
|---|---|
| `source_type` | entity the edge attaches to |
| `assoc_table` | the link/association table |
| `match_columns` | pipe-joined columns forming the owner's key |
| `match_resolver` | `entity_key` (owner's natural key) or `ontology_term` (owner is a CV node) |
| `value_columns` | pipe-joined columns carrying the target reference |
| `value_resolver` | `ontology_term`, `entity_guid`, or `raw` |
| `value_entity` | for `entity_guid`: the table whose node the value resolves to; for `ontology_term`: the CV source table |
| `target_property` | pipe-joined target properties the edge writes |
| `wrap` | `ident_ref`, `property_value`, `ruled_out_pv` |
| `filter_column` | gate the rows on this column (blank = no filter) |
| `filter_endswith` | keep rows whose `filter_column` ends with this (`:1` observed, `:0` ruled-out — **the CV code, never the label**) |
| `param_name` | name for the wrapped `PropertyValue` when `wrap` = `property_value` (the old `pv_name`) |
| `note` | free text |

A single association row is written twice in the CSV to express both an edge and
its back-reference (swap which columns are `match` vs `value`), exactly as the
original per-table JSON did.

---

## `cv_bases.csv` — controlled-vocabulary → ontology IRI bases (c2m2 only)

The prefix/table → ontology-base lookup that `ontology.resolve_term` used to
hold as Python dicts. Two kinds of row:

| column | meaning |
|---|---|
| `key` | the CURIE prefix (`kind=curie`, e.g. `DOID`) or the CV table (`kind=bare`, e.g. `gene`) |
| `kind` | `curie` (value carries a CURIE prefix) or `bare` (table's ids are bare accessions) |
| `iri_base` | IRI base the local id is appended to (e.g. `http://purl.obolibrary.org/obo/DOID_`) |
| `ontology_name` | human name of the ontology |
| `curie_prefix` | for `kind=bare`: the CURIE stem to reattach (e.g. `ensembl`) |
| `note` | free text |

A few resolutions stay in plugin code because they are not simple base lookups:
the `NCBI:txid…` taxonomy rule and the GlyTouCan-vs-PubChem `compound` split.

---

## Parsers and plugin methods (the Python that a CSV references by name)

**Parsers** all share one signature:

```python
def parser(value, rule, ctx) -> parsed_value | None
```

`value` is the source property value (`None` for synthesized fields), `rule` is
the compiled row (the CSV columns), and `ctx` carries conversion state (the
current node, the `@id`→node index, the guid map, the root node, and any
per-plugin extras). Returning `None` means "set nothing." Parsers are registered
by name in the plugin class's `import_parsers` / `export_parsers` dicts, so the
loader can reject a typo in a CSV at load time. Shared building blocks live in
`core/parsers.py`.

**Plugin methods** are the per-workflow orchestration — override them on your
`PluginBase` subclass (full list + when to override each: `docs/NEW-PLUGIN.md`):

| method | what it does | examples |
|---|---|---|
| `load_source` | turn the raw input into `SourceRecord`s (the common override) | example; helpers `records_from_items` / `records_from_graph` |
| `classify` / `discriminators` | match a record to its `entities.csv` row, gated by named predicates | wrroc workflow-vs-tool discriminator |
| `pre` | full-control record production: build indexes, mint ARKs, load join/CV tables | c2m2 guid-map + association index; wrroc id minting |
| `map_record` | **engine default** applies the property rules; override only when a record doesn't map rule-by-rule | d4d many-to-one merge; c2m2 vars pipeline |
| `link` | cross-node edges added after all nodes exist | wrroc `isPartOf` / `generatedBy` mirroring |
| `assemble` | build the root, attach children, write preservation files | c2m2 root + datapackage/sqlite copy |
| `export` | bespoke reverse driver or engine bypass | wrroc/d4d reverse; croissant |

A plugin implements only the steps it needs; the rest default to the engine's
generic behaviour. Property-rule application is the engine's own code unless a
plugin genuinely cannot map rule-by-rule — which is the whole point of the
format.

---

## Worked rows (one per plugin)

**wrroc** `entities.csv` — a workflow-level run becomes an EVI Computation:
```
source_type,discriminator,target_type,target_type_iri,level,id_strategy,id_template,id_column,keep_identifier,mint_prefix,note
CreateAction,instrument_is_workflow,Computation,prov:Activity|https://w3id.org/EVI#Computation,workflow,mint,,,TRUE,computation-main,parent run
```
wrroc `properties.csv` — description synthesized to satisfy EVI's min-length:
```
source_type,source_property,target_type,target_property,import_parser,export_parser,direction,reverse_primary,requirement,cardinality,constant_value,fallback_source,fallback_parser,source_table,param_name,wrap,note
CreateAction,description,Computation,description,desc_min10,scalar,both,TRUE,synthesized,scalar,,,,,,,
```

**d4d** `entities.csv` — a distribution becomes a DigitalObject graph node
(d4d reuses `target_type_iri` for the additionalType and `id_column` for the
url field):
```
distributions,,DigitalObject,distribution,data,keep,,download_url,FALSE,,each distribution -> DigitalObject in hasPart
```
d4d `properties.csv` — one of the many sources merging onto `rai_data_use_cases`:
```
D4D,intended_uses,Dataset,rai_data_use_cases,flatten,reverse_flatten,both,TRUE,recommended,list,,,,,,,
```

**c2m2** `entities.csv` — the biosample table explodes to EVI Samples (c2m2's
file adds a `precedence` column before `note`; d4d/wrroc's files don't have it):
```
biosample,,Sample,,data,persistent_ark_or_mint,{prefix}-biosample/{local_id},persistent_id,FALSE,,20,
```
c2m2 `associations.csv` — observed disease edges only:
```
source_type,assoc_table,match_columns,match_resolver,value_columns,value_resolver,value_entity,target_property,wrap,filter_column,filter_endswith,param_name,note
biosample,biosample_disease,biosample_id_namespace|biosample_local_id,entity_key,disease,ontology_term,disease,associatedDisease,ident_ref,association_type,:1,,
```

**croissant** `entities.csv` — the root crate becomes a Croissant Dataset (export-only):
```
ROCrateMetadataElem,ROOT,CroissantDataset,,root,keep,,,FALSE,,0,the crate root -> Croissant Dataset
```
croissant `properties.csv` — encodingFormat mapped to a MIME type on export:
```
Dataset,format,CroissantFileObject,encodingFormat,,map_format_to_mime_type,export,FALSE,,scalar,,,,,,,
```

**example** `entities.csv` + `properties.csv` — the minimal plugin
(`plugins/example/`), a toy memo becoming a schema.org Dataset:
```
memo,,Dataset,https://schema.org/Dataset,data,keep,,,FALSE,,one Dataset per memo
memo,title,Dataset,name,scalar,,import,,required,scalar,,,,,,,
```
