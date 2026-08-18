# Adding a new plugin

A plugin is a folder under `plugins/` holding **CSV mapping data** plus **one
`PluginBase` subclass**. The rule of thumb from the README applies to
everything you write: *if it is data it lives in a CSV; if it is an algorithm
it is a named parser or a method on your plugin class.*

The fastest path: **copy `plugins/example/` and edit** — it is the smallest
working plugin (a toy "memo" format), tested by `tests/test_example.py`, and
every step below points back to it.

```
plugins/yourformat/
  entities.csv      what each source thing becomes, how its @id is chosen
  properties.csv    which source fields land where, via which named parser
  __init__.py       class YourFormatPlugin(PluginBase) + convert() wrapper
  parsers.py        (only if you need parsers core.parsers doesn't have)
  input.json        a small representative source document
  golden.json       the expected conversion of input.json
```

## 1. Write `entities.csv`

One row per source entity class (a table, a node `@type`, a field holding a
list of objects). The columns are specified in `MAPPING-SCHEMA.md`; the ones
you almost always need:

```csv
source_type,discriminator,target_type,target_type_iri,level,id_strategy,id_template,id_column,keep_identifier,mint_prefix,note
memo,,Dataset,https://schema.org/Dataset,data,keep,,,FALSE,,one Dataset per memo
```

- `source_type` is the name your `load_source` gives each record (or a node's
  `@type` for graph sources).
- `id_strategy` `keep` reuses the source id; `mint` + `id_template` builds one
  by `{token}` interpolation against the record.
- Row order is match precedence — first matching row wins.

## 2. Write `properties.csv`

One row moves one property. Again see `MAPPING-SCHEMA.md` for every column:

```csv
source_type,source_property,target_type,target_property,import_parser,export_parser,direction,...
memo,title,Dataset,name,scalar,,import,...
memo,tags,Dataset,keywords,string_list,,import,...
```

`import_parser` / `export_parser` are **names**; step 4 is where the names get
implementations. A name no parser implements fails at import time — you cannot
typo a CSV silently.

## 3. Subclass `PluginBase`

```python
from ...core import Context, PluginBase, SourceRecord, records_from_items
from ...core.parsers import scalar, string_list

class YourFormatPlugin(PluginBase):
    name = "yourformat"
    import_parsers = {"scalar": scalar, "string_list": string_list}

    def load_source(self, source):
        # how to read YOUR format: yield SourceRecords
        return records_from_items({"memo": source["memos"]}, id_key="id")

    def assemble(self, ctx: Context):
        # how to wrap the mapped nodes into the final document
        return {"@graph": [ctx.out_nodes[i] for i in ctx.order]}

PLUGIN = YourFormatPlugin()

def convert(direction, source):
    return PLUGIN.convert(direction, source)
```

That's a complete import pipeline. The base class runs
`pre → map → link → assemble`; you supplied the two steps it can't guess.

**`load_source`** turns your raw input into `SourceRecord`s. Two helpers cover
the common shapes:

- `records_from_items({"memo": rows, ...}, id_key="id")` — dict-of-lists; each
  record carries its `source_type` explicitly.
- `records_from_graph(crate["@graph"])` — JSON-LD; records carry
  `source_type=""` and are classified by their node's `@type` instead.

Everything else defaults sensibly: classification walks `entities.csv` in
order; property mapping applies your `properties.csv` rules first-match-wins;
`@id` follows `id_strategy`; duplicate `@id`s are dropped (first writer wins).

## 4. Parsers

Every parser has the one signature `fn(value, rule, ctx) -> value | None`
(`None` = set nothing). Reach for `core/parsers.py` first (`scalar`,
`string_list`, `identity`, `drop`, `constant(...)`). Anything format-specific
goes in your own `parsers.py` and into the class registries:

```python
def parse_semver(value, rule, ctx):
    return str(value).lstrip("v") if value else None

class YourFormatPlugin(PluginBase):
    import_parsers = {"scalar": scalar, "semver": parse_semver, ...}
```

`rule` is the compiled CSV row (so a parser can read `rule.source_property`,
`rule.constant_value`, …); `ctx` is the conversion state (section below).

## 5. Run it

```python
from fairscape_conversion.plugins import yourformat
crate = yourformat.convert("import", source_dict)
```

or `python3 -m fairscape_conversion.core.cli convert yourformat import in.json out.json`
(JSON/YAML picked by extension).

## 6. Test it (golden file — no reference converter needed)

Commit `input.json` and the expected `golden.json` in your plugin folder, then
copy `tests/test_example.py`:

```python
def test_yourformat_import_matches_golden():
    from fairscape_conversion.plugins import yourformat
    assert yourformat.convert("import", _load("input.json")) == _load("golden.json")
```

Generate `golden.json` by running the conversion once and **reviewing the
output by hand** before committing it. Run the tests from the package
directory: `python3 -m pytest tests/ -q`.

## Going further — the other overridable steps

Override only what your workflow genuinely needs; each existing plugin is the
worked example named below.

| method | override when | example |
|---|---|---|
| `setup(ctx)` | you need indexes/minted ids before records exist | — (wrroc does this inside `pre`) |
| `load_source(source)` | always, for the common case | example |
| `classify(ctx, sr)` | matching needs more than type + discriminator | — |
| `discriminators = {...}` | an `entities.csv` row is gated by a predicate `fn(node, ctx) -> bool` | wrroc `instrument_is_workflow` |
| `pre(ctx)` | loading, classification, and id minting interleave — full control over `ctx.records` | wrroc, d4d, c2m2 |
| `select_rules(ctx, rec)` | a record's rules aren't "all rules for its target type" | d4d (returns `[]`) |
| `map_record(ctx, rec, rules)` | a record doesn't map rule-by-rule | d4d (many-to-one merge), c2m2 (vars pipeline) |
| `resolve_id(ctx, rec)` | `@id` needs more than `guid_map`/`id_strategy` | — |
| `link(ctx)` | cross-node edges need every node to exist first | wrroc (`generatedBy` inverses) |
| `assemble(ctx)` | always | all |
| `export(source, options)` | the reverse trip is bespoke (own driver composing `apply_export_rules`) or bypasses the engine entirely | wrroc / d4d; croissant |
| `configure()` | one-time setup after the mapping loads | c2m2 (cv_bases → ontology tables) |
| `import_` / `export` raising | one-way plugins | croissant, c2m2 |

## `ctx` cheat-sheet

`ctx` is a `core.engine.Context` — the mutable state every parser and method
receives:

| field | meaning |
|---|---|
| `ctx.source` | the raw input passed to `convert` |
| `ctx.mapping` | the loaded CSVs (`entities`, `properties`, selectors) |
| `ctx.records` | the queue `pre` fills: `Record(data, rule, source_id)` |
| `ctx.by_id` | source `@id` → source node (graph plugins fill it in `pre`) |
| `ctx.root` | the source's root node, if the plugin sets it |
| `ctx.out_nodes` / `ctx.order` | mapped nodes by `@id` + emission order (what `assemble` reads); pre-seed them to reserve ids |
| `ctx.extras` | **the plugin scratchpad.** Per-run `convert(**options)` land here; stash anything later steps need |
| `ctx.node` / `ctx.node_extras` | set per record during mapping: the record being mapped + side outputs merged into it |

Well-known `ctx.extras` keys (conventions, not magic — except `guid_map`,
which `resolve_id` honours):

| key | who sets it | meaning |
|---|---|---|
| `validate` | caller option | run pydantic crate validation in `assemble` (wrroc, d4d) |
| `naan` | caller option | ARK namespace for minting (wrroc, c2m2) |
| `guid_map` | `pre` | source id → minted `@id`; the default `resolve_id` checks it first |
| `output_path`, `author`, … | caller options | c2m2 file output + root overrides |

## Known wart

c2m2's `configure()` rebuilds lookup tables by assigning module globals in its
`ontology.py` (ported behaviour, asserted by its parity tests). Don't copy that
pattern in a new plugin — keep derived state on `self` or in `ctx.extras`.
