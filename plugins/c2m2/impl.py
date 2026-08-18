#!/usr/bin/env python3
"""C2M2 -> RO-Crate conversion: ``C2m2Plugin`` on the shared pipeline.

The plugin is self-contained: the engine machinery lives in the plugin-local
``mapper`` / ``parsers`` / ``ontology`` modules (ported verbatim from the
standalone ``c2m2-rocrate`` converter, which stays untouched as the parity
reference) and runs through the shared pipeline:

  pre         resolve meta, read each TSV once, pre-load the per-table
              reflection nodes (Dataset + evi:Schema), build the guid maps and
              the association index, queue one record per mapped table row
  map_record  the ported ``_build_node``: vars -> minted @id (None drops the
              row) -> constants -> fields -> additional_property -> association
              attach on the dual keyspace -> extra_type -> pydantic validation
  assemble    preservation file nodes, Computation/Software provenance, the
              declarative root, whole-crate validation, file writes

The mapping source is the shared ``Mapping`` (entities/properties/associations
loaded by the fairscape_conversion loader) plus the plugin-local ``constants.csv`` /
``computed.csv``; ``_cfgs_from_mapping`` compiles them into the per-table cfg
dicts the ported machinery consumes. ``root.json`` (crate identity / root
fields) is structural, not row-mapping data, and stays JSON.
"""

from __future__ import annotations

import csv
import json
import pathlib

from fairscape_models.biochem_entity import BioChemEntity
from fairscape_models.dataset import Dataset
from fairscape_models.defined_term import DefinedTerm
from fairscape_models.medical_condition import MedicalCondition
from fairscape_models.patient import Patient
from fairscape_models.sample import Sample

from ...core import Context, PluginBase, Record
from . import ontology
from .mapper import C2M2Mapper, CONTEXT, DEFAULT_LICENSE, DEFAULT_NAAN, _dump
from .parsers import (build_vars, dedup_ident_refs, interp, interp_value,
                      match_key, meta_tokens, mint_id, passes_filter,
                      resolve_value, wrap_value, PARSERS, _key)

HERE = pathlib.Path(__file__).resolve().parent

# entity_type -> pydantic model. Every model's default @type normalizes into
# ROCrateV1_2.type_map, so a node built here never silently degrades to
# GenericMetadataElem (guarded when the cfgs load).
ENTITY_MODELS = {
    "Patient": Patient,
    "Sample": Sample,
    "MedicalCondition": MedicalCondition,
    "BioChemEntity": BioChemEntity,
    "DefinedTerm": DefinedTerm,
    "Dataset": Dataset,
}

_ADDITIONAL_PROPERTY = "additionalProperty"


# ============================================================================
# Mapping source: the unified CSVs -> per-table cfg dicts
# ============================================================================

def _read_csv(name):
    path = HERE / name
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def _pipe(cell):
    return [p for p in (cell or "").split("|") if p]


# Which literal param each field parser carries in constant_value / fallback_source.
_LITERAL_PARAM = {"scalar_default": "default", "description_or_template": "template",
                  "template": "template"}


def _cfgs_from_mapping(mapping):
    """Shared Mapping + plugin-local constants/computed CSVs -> per-table cfg dicts."""
    consts = _read_csv("constants.csv")
    comps = _read_csv("computed.csv")

    cfgs = []
    for e in mapping.entities:
        table = e.source_type
        etype = e.target_type
        cfg = {"source_table": table, "entity_type": etype, "order": e.precedence}
        if e.level == "generated":
            cfg["generated"] = True

        # extra_type
        extra = {c["property"]: (json.loads(c["value_json"]) if c["value_json"] else c["value"])
                 for c in consts if c["source_type"] == table and c["kind"] == "extra_type"}
        if extra:
            cfg["extra_type"] = extra

        # computed
        computed = {}
        for c in comps:
            if c["source_type"] != table:
                continue
            if c["strategy"] == "first_nonempty":
                computed[c["token"]] = {"first_nonempty": _pipe(c["sources"])}
            else:
                spec = {"template": c["template"]}
                if c["when"]:
                    spec["when"] = c["when"]
                computed[c["token"]] = spec
        if computed:
            cfg["computed"] = computed

        # cv_source (DefinedTerm tables expose {curie}/{onto}/{iri})
        if etype == "DefinedTerm":
            cfg["cv_source"] = {"column": e.id_column or "id", "source_table": table}

        # id
        idc = {"strategy": e.id_strategy, "column": e.id_column}
        if e.id_template:
            idc["mint"] = e.id_template
        if e.id_strategy == "ontology_term":
            idc["source_table"] = table
        cfg["id"] = idc

        # constants
        constants = {c["property"]: (json.loads(c["value_json"]) if c["value_json"] else c["value"])
                     for c in consts if c["source_type"] == table and c["kind"] == "constant"}
        if constants:
            cfg["constants"] = constants

        # fields + additional_property (preserve CSV row order)
        fields, additional = [], []
        for p in mapping.properties:
            if p.source_type != table:
                continue
            parser = p.import_parser
            if p.target_property == "additionalProperty":
                ap = {"name": p.param_name, "parser": parser}
                if p.source_property:
                    ap["source"] = p.source_property
                if p.constant_value:
                    ap["const"] = p.constant_value
                if p.source_table:
                    ap["source_table"] = p.source_table
                additional.append(ap)
            else:
                fld = {"source": p.source_property or "", "target": p.target_property,
                       "parser": parser}
                if parser in _LITERAL_PARAM and p.constant_value:
                    fld[_LITERAL_PARAM[parser]] = p.constant_value
                if parser == "first_nonempty" and p.fallback_source:
                    fld["fallbacks"] = _pipe(p.fallback_source)
                if p.source_table:
                    fld["source_table"] = p.source_table
                fields.append(fld)
        if fields:
            cfg["fields"] = fields
        if additional:
            cfg["additional_property"] = additional

        # associations (preserve CSV row order)
        associations = []
        for a in mapping.associations:
            if a.source_type != table:
                continue
            match = {"columns": list(a.match_columns), "resolver": a.match_resolver}
            if a.match_resolver == "ontology_term":
                match["source_table"] = table
            value = {"columns": list(a.value_columns), "resolver": a.value_resolver}
            if a.value_resolver == "ontology_term":
                value["source_table"] = a.value_entity
            elif a.value_resolver == "entity_guid":
                value["entity"] = a.value_entity
            rule = {"assoc_table": a.assoc_table, "match": match, "value": value,
                    "targets": list(a.target_property), "wrap": a.wrap}
            if a.filter_column:
                rule["filter"] = {"column": a.filter_column, "endswith": a.filter_endswith}
            if a.param_name:
                rule["pv_name"] = a.param_name
            associations.append(rule)
        if associations:
            cfg["associations"] = associations

        cfgs.append(cfg)

    cfgs.sort(key=lambda c: c.get("order", 0))
    return cfgs


def _load_cfgs(mapping):
    root_cfg = json.loads((HERE / "root.json").read_text())
    entity_cfgs = _cfgs_from_mapping(mapping)
    for cfg in entity_cfgs:
        if cfg["entity_type"] not in ENTITY_MODELS:
            raise ValueError(
                f"{cfg['source_table']}: entity_type {cfg['entity_type']!r} is not one of "
                f"{sorted(ENTITY_MODELS)}; an unknown @type would silently degrade to "
                f"GenericMetadataElem.")
    return root_cfg, entity_cfgs


# ============================================================================
# guid maps + association index (built in ``pre``, before any node is emitted)
# ============================================================================

def _build_guid_maps(mapper, meta, entity_cfgs):
    """(id_namespace, local_id) -> node @id, for every opaque-minting table."""
    guid_maps = {}
    for cfg in entity_cfgs:
        table = cfg["source_table"]
        if table not in meta["populated"]:
            continue
        if cfg["id"]["strategy"] not in ("persistent_or_mint", "persistent_ark_or_mint", "mint", "column"):
            continue
        gm = {}
        for row in mapper._read_tsv(table):
            vars = build_vars(cfg, row, meta)
            gid = mint_id(cfg["id"], row, vars, meta)
            if gid:
                gm[_key(row.get("id_namespace"), row.get("local_id"))] = gid
        guid_maps[table] = gm
    return guid_maps


def _build_assoc_index(mapper, meta, guid_maps, entity_cfgs):
    """source_table -> ordered list of (target, {match_key -> [wrapped values]}).

    Built once from every mapping's ``associations`` rules; empty/missing assoc
    tables no-op. Kept in declaration order so additionalProperty edges attach
    predictably.
    """
    index = {}
    for cfg in entity_cfgs:
        entries = []
        for rule in cfg.get("associations", []):
            targets = rule["targets"]
            per_target = {t: {} for t in targets}
            for row in mapper._read_tsv(rule["assoc_table"]):
                if not passes_filter(rule.get("filter"), row):
                    continue
                mkey = match_key(rule["match"], row, meta, guid_maps)
                vid = resolve_value(rule["value"], row, meta, guid_maps)
                if mkey is None or vid is None:
                    continue
                for target in targets:
                    wrapped = wrap_value(rule["wrap"], vid, rule, target)
                    if wrapped is None:
                        continue
                    per_target[target].setdefault(mkey, []).append(wrapped)
            for target in targets:
                entries.append((target, per_target[target]))
        index[cfg["source_table"]] = entries
    return index


# ============================================================================
# One row -> one node dict
# ============================================================================

def _build_node(cfg, row, meta, assoc_index):
    vars = build_vars(cfg, row, meta)
    guid = mint_id(cfg["id"], row, vars, meta)
    if not guid:
        return None
    vars["guid"] = guid
    ctx = {"row": row, "vars": vars, "meta": meta}

    element = {"@id": guid}

    for prop, value in cfg.get("constants", {}).items():
        element[prop] = interp_value(value, vars)

    for field in cfg.get("fields", []):
        raw = row.get(field["source"]) if field.get("source") else None
        result = PARSERS[field["parser"]](raw, field, ctx)
        if result is not None:
            element[field["target"]] = result

    additional = []
    for ap in cfg.get("additional_property", []):
        raw = row.get(ap["source"]) if ap.get("source") else None
        pv = PARSERS[ap["parser"]](raw, ap, ctx)
        if pv is not None:
            additional.append(pv)

    # Attach declared association edges. A node is looked up by BOTH its entity key (tuple) and
    # its @id (string); the two key spaces are disjoint, so a mapping never has to restate which
    # key its own associations use.
    entity_key = None
    if "id_namespace" in row and "local_id" in row:
        entity_key = _key(row.get("id_namespace"), row.get("local_id"))
    for target, keymap in assoc_index.get(cfg["source_table"], []):
        values = []
        if entity_key is not None:
            values += keymap.get(entity_key, [])
        values += keymap.get(guid, [])
        if not values:
            continue
        if target == _ADDITIONAL_PROPERTY:
            additional.extend(values)
        else:
            element[target] = dedup_ident_refs(element.get(target, []) + values)

    if additional:
        element["additionalProperty"] = additional
    if cfg.get("extra_type"):
        element.update(interp_value(cfg["extra_type"], vars))
    return element


# ============================================================================
# Root (declarative, from root.json)
# ============================================================================

def _build_root(root_cfg, meta, populated, total_tables, element_guids, overrides):
    from fairscape_models.rocrate import ROCrateMetadataElem

    vars = dict(meta_tokens(meta))
    vars.update({
        "populated_list": ", ".join(sorted(populated)),
        "total_tables": str(total_tables),
        "tables_populated": str(len(populated)),
        "empty_count": str(total_tables - len(populated)),
    })
    computed = {
        "cfde_and_namespaces": meta["isPartOf"],
        "all_element_guids": [{"@id": g} for g in element_guids],
        "tables_total": total_tables,
        "tables_populated": len(populated),
        "today_or_arg": meta["date"],
        "version_arg": overrides.get("version") or "1.0",
        "license_arg": overrides.get("license") or DEFAULT_LICENSE,
        "identifier_arg": overrides.get("identifier"),
    }
    element = {}
    for prop, spec in root_cfg["fields"].items():
        value = _resolve_root_field(spec, vars, computed, overrides, meta)
        if value is not None:
            element[prop] = value
    return ROCrateMetadataElem.model_validate(element)


def _resolve_root_field(spec, vars, computed, overrides, meta):
    # Source branches are tried in precedence order (override > meta > const > template >
    # computed), falling through on a None result so a field can declare a fallback chain --
    # e.g. name = override("$name_arg") -> meta("project_name") -> template(dcc default).
    override = spec.get("override")
    if override:
        key = override[1:].replace("_arg", "") if override.startswith("$") else override
        if overrides.get(key) is not None:
            return overrides[key]
    if "meta" in spec:
        value = meta.get(spec["meta"])
        if value is not None:
            return value
    if "const" in spec:
        value = interp_value(spec["const"], vars)
        if value is not None:
            return value
    if "template" in spec:
        value = interp(spec["template"], vars)
        if value is not None:
            return value
    if "computed" in spec:
        value = computed.get(spec["computed"])
        return value if value is not None else spec.get("default")
    return None


# ============================================================================
# The plugin
# ============================================================================

class C2m2Plugin(PluginBase):
    """CFDE C2M2 Frictionless datapackage -> FAIRSCAPE RO-Crate (import-only).

    Only the shell is PluginBase-shaped; the row/CV/association machinery is
    the ported standalone converter, untouched to preserve parity.
    """

    name = "c2m2"
    import_parsers = PARSERS   # loader name-validation; dispatch happens in _build_node
    export_parsers = {}

    def configure(self):
        """Rebuild the ontology module's CV -> IRI-base lookup tables from
        ``cv_bases.csv`` (the authoritative source).

        Known wart: this mutates ``ontology`` module globals, exactly like the
        original converter — ``test_cv_bases_reproduce_ontology`` asserts those
        globals, so threading the lookups through every resolver is
        deliberately out of scope.
        """
        curie, bare, bare_prefix = {}, {}, {}
        for cb in self.mapping.cv_bases:
            if cb.kind == "curie":
                curie[cb.key] = (cb.iri_base, cb.ontology_name)
            else:
                bare[cb.key] = (cb.iri_base, cb.ontology_name)
                bare_prefix[cb.key] = cb.curie_prefix
        ontology._CURIE_BASES = curie
        ontology._BARE_TABLE_BASES = bare
        ontology._BARE_CURIE_PREFIX = bare_prefix

    def export(self, source, options: dict):
        raise ValueError("c2m2 is import-only (C2M2 -> RO-Crate)")

    def pre(self, ctx: Context):
        """Read the datapackage TSVs once, build guid maps + the association
        index, seed the per-table reflection nodes, queue one record per row
        (full-control override)."""
        mapper = C2M2Mapper(ctx.source)
        root_cfg, entity_cfgs = _load_cfgs(ctx.mapping)
        naan = ctx.extras.get("naan") or str(root_cfg.get("identity", {}).get("naan", DEFAULT_NAAN))
        meta = mapper._resolve_metadata(ctx.extras.get("author"), ctx.extras.get("publisher"),
                                        ctx.extras.get("date_published"), naan)

        output_path = ctx.extras.get("output_path")
        if output_path is None:
            slug = meta["prefix"].rsplit("/", 1)[-1]
            output_path = mapper.dir / f"{slug}-crate"
        output_path = pathlib.Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)
        meta["output_path"] = str(output_path)

        populated = mapper._populated_tables()
        meta["populated"] = set(populated)

        # Per-table reflection layer (Dataset + evi:Schema from the Frictionless
        # descriptor). Pre-loaded into out_nodes/order so their guids seed the
        # first-wins dedup — exactly the old engine's `seen` set semantics.
        generated_guids = []
        for resource in mapper.resources:
            table = resource["name"]
            if table not in meta["populated"]:
                continue
            for obj in (mapper._schema_element(resource, meta), mapper._table_dataset(resource, meta)):
                node = _dump(obj)
                ctx.out_nodes[node["@id"]] = node
                ctx.order.append(node["@id"])
                generated_guids.append(node["@id"])

        guid_maps = _build_guid_maps(mapper, meta, entity_cfgs)
        assoc_index = _build_assoc_index(mapper, meta, guid_maps, entity_cfgs)

        ctx.extras.update(
            mapper=mapper,
            meta=meta,
            root_cfg=root_cfg,
            populated=populated,
            guid_maps=guid_maps,
            assoc_index=assoc_index,
            generated_guids=generated_guids,
            cfg_by_table={c["source_table"]: c for c in entity_cfgs},
            output_path=output_path,
        )

        records = []
        for cfg in entity_cfgs:
            table = cfg["source_table"]
            if table not in meta["populated"]:
                continue
            rule = ctx.mapping.entity_for(table)
            if rule is None:
                raise ValueError(f"no entities.csv row for mapped table {table!r}")
            records.extend(Record(data=row, rule=rule) for row in mapper._read_tsv(table))
        ctx.records = records

    def map_record(self, ctx: Context, rec: Record, rules):
        cfg = ctx.extras["cfg_by_table"][rec.rule.source_type]
        node = _build_node(cfg, rec.data, ctx.extras["meta"], ctx.extras["assoc_index"])
        # The dedup check runs here (not just in the engine loop) so a duplicate
        # @id also skips validation and the generated-guid bookkeeping, exactly
        # like the old engine's `seen` check.
        if node is None or node["@id"] in ctx.out_nodes:
            return None
        obj = ENTITY_MODELS[cfg["entity_type"]].model_validate(node)
        if cfg.get("generated"):
            ctx.extras["generated_guids"].append(obj.guid)
        return _dump(obj)

    def assemble(self, ctx: Context) -> dict:
        from fairscape_models.rocrate import ROCrateV1_2

        mapper = ctx.extras["mapper"]
        meta = ctx.extras["meta"]
        populated = ctx.extras["populated"]
        output_path = ctx.extras["output_path"]
        total_tables = len(mapper.resources)

        # Preservation layer + provenance pair, appended after the mapped nodes.
        tail = []
        used_dataset_guids = []
        datapackage_element = mapper._preserved_file(
            mapper.datapackage_path, f"{meta['prefix']}-datapackage-json",
            "frictionless-datapackage-descriptor", "application/json", meta,
            description=(
                f"The Frictionless Data Package descriptor (JSON Table Schema) defining "
                f"all {total_tables} C2M2 table fields, primary keys, and foreign-key "
                f"relationships for this instance — the authoritative relational contract, "
                f"preserved verbatim so the full model survives even for tables omitted "
                f"from @graph."
            ),
        )
        tail.append(_dump(datapackage_element))
        used_dataset_guids.append(datapackage_element.guid)

        preserve_sqlite = ctx.extras.get("include_sqlite", True) and mapper.sqlite_path.exists()
        if preserve_sqlite:
            sqlite_element = mapper._preserved_file(
                mapper.sqlite_path, f"{meta['prefix']}-datapackage-sqlite",
                "relational-index", "application/vnd.sqlite3", meta,
                description=(
                    "A prebuilt SQLite database containing every C2M2 table for this "
                    "instance with primary/foreign keys enforced — a ready-to-query "
                    "relational index. Preserved verbatim so a future system can rebuild "
                    "the CFDE index from the crate alone, without the live DERIVA/ERMrest "
                    "catalog."
                ),
            )
            tail.append(_dump(sqlite_element))
            used_dataset_guids.append(sqlite_element.guid)

        software = mapper._software(meta)
        computation = mapper._computation(meta, ctx.extras["generated_guids"], used_dataset_guids)
        tail.extend([_dump(computation), _dump(software)])

        element_guids = list(ctx.order) + [n["@id"] for n in tail]
        overrides = {k: ctx.extras.get(k)
                     for k in ("name", "description", "keywords", "version", "license", "identifier")}
        root = _build_root(ctx.extras["root_cfg"], meta, populated, total_tables,
                           element_guids, overrides)
        descriptor = root.generateFileElem()

        graph = [_dump(descriptor), _dump(root)] + [ctx.out_nodes[g] for g in ctx.order] + tail
        crate = {"@context": CONTEXT, "@graph": graph}

        ROCrateV1_2.model_validate(json.loads(json.dumps(crate)))

        with (output_path / "ro-crate-metadata.json").open("w", encoding="utf-8") as f:
            json.dump(crate, f, indent=2)
        mapper._copy_preservation_files(output_path, populated, preserve_sqlite)
        return crate
