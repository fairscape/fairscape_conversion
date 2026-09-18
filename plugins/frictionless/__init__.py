#!/usr/bin/env python3
"""frictionless plugin — a Frictionless Data Package -> FAIRSCAPE EVI RO-Crate.

A Data Package (https://datapackage.org) is a ``datapackage.json`` listing
*resources*; a tabular resource carries a *Table Schema* (typed fields with
constraints, keys, missing values). It is how ICPSR-style deposits, open
government data and a lot of social-science datasets are already
described, so nothing needs re-entering:

    convert("import", "path/to/package/")          # dir holding datapackage.json
    convert("import", "path/to/datapackage.json")
    convert("import", descriptor_dict)             # parsed descriptor, nothing on disk
    convert("import", records)                      # pre-extracted (extract.py)

The crate holds one **Dataset** per resource (name, description, format,
size, hash, license, local path or URL), one **Schema** per resource with a
Table Schema (each field -> an EVI Property: type from ``field_types.csv``,
constraints -> JSON-Schema keywords, ``rdfType`` -> ``valueURL``; keys and
missing-value markers pass through), and a Dataset for the descriptor
itself when the package came from disk. The root takes the package's
title, description, keywords, licence and contributors.

No provenance is asserted: a Data Package says what its files are, not how
they were made, and inventing a Computation would be a lie. ARKs hash the
package's ``name@version`` (Frictionless's own identity) so re-converting
the same package reproduces them.

Export (``convert("export", crate)``) goes the other way for any EVI crate:
the root becomes the package, each Dataset a resource, and each Dataset's
``evi:Schema`` a Table Schema — so a crate made by the redcap, mlflow or
snakemake plugins can be deposited as a Data Package. Computations and
Software have no Data Package home and are left out.

C2M2 is one profile of this format with fixed table names and ontology
columns; it keeps its own plugin (``plugins/c2m2``). This one takes any
package.
"""

from __future__ import annotations

import os

from ...core import (Context, PluginBase, Record, apply_export_rules,
                     apply_import_rules)
from ...core.arks import mint_ark
from .extract import extract as extract_records
from .parsers import (EXPORT_PARSERS, IMPORT_PARSERS, license_entry,
                      resource_slug)

EVI = "https://w3id.org/EVI#"

DEFAULT_CONTEXT = {
    "@vocab": "https://schema.org/",
    "evi": "https://w3id.org/EVI#",
    "rai": "http://mlcommons.org/croissant/RAI/",
    "prov": "http://www.w3.org/ns/prov#",
    "usedSoftware": {"@id": EVI + "usedSoftware", "@type": "@id"},
    "usedDataset": {"@id": EVI + "usedDataset", "@type": "@id"},
    "generatedBy": {"@id": EVI + "generatedBy", "@type": "@id"},
    "generated": {"@id": EVI + "generated", "@type": "@id"},
    "hasDistribution": {"@id": EVI + "hasDistribution", "@type": "@id"},
    "localPath": "https://w3id.org/ro/terms#localPath",
}
SCHEMA_CONTEXT = {"@vocab": "https://schema.org/", "evi": "https://w3id.org/EVI#"}


class FrictionlessPlugin(PluginBase):
    name = "frictionless"
    import_parsers = IMPORT_PARSERS
    export_parsers = EXPORT_PARSERS

    def pre(self, ctx: Context) -> None:
        """Mint an ARK per resource (and per Table Schema) from the package
        key, and queue records: schemas first so a Dataset can point at
        its Schema, then resources, then the descriptor file."""
        src = ctx.source
        naan = src["settings"]["naan"]
        key = src["package"]["key"]
        title = src["settings"]["name"]

        guid_map = {"root": mint_ark(naan, "rocrate", title, key)}
        rule_for = {e.source_type: e for e in ctx.mapping.entities}
        schemas, resources = [], []
        for i, res in enumerate(src["resources"]):
            rname = res.get("name") or os.path.basename(str(res.get("path") or f"resource-{i}"))
            res = {**res, "name": rname}
            guid_map["resource:" + rname] = mint_ark(naan, "dataset", rname, key + "#" + rname)
            resources.append(Record(res, rule_for["resource"], "resource:" + rname))
            if (res.get("schema") or {}).get("fields"):
                guid_map["schema:" + rname] = mint_ark(naan, "schema", rname,
                                                       key + "#" + rname + "#schema")
                schemas.append(Record(res, rule_for["schema"], "schema:" + rname))
        if src.get("descriptor_file"):
            guid_map["descriptor"] = mint_ark(naan, "dataset", src["descriptor_file"]["file"],
                                              key + "#descriptor")
        ctx.extras["guid_map"] = guid_map

        records = schemas + resources
        if src.get("descriptor_file"):
            records.append(Record(src["descriptor_file"], rule_for["descriptor"], "descriptor"))
        ctx.records = records

    def select_rules(self, ctx: Context, rec: Record):
        return ctx.mapping.import_rules_by_source(rec.rule.source_type)

    def map_record(self, ctx: Context, rec: Record, rules):
        node = {"@id": ctx.extras["guid_map"][rec.source_id]}
        if rec.rule.source_type == "schema":
            node["@context"] = SCHEMA_CONTEXT
        iri = list(rec.rule.target_type_iri)
        node["@type"] = iri if len(iri) > 1 else iri[0]
        node.update(apply_import_rules(rec.data, rules, ctx))
        return node

    def assemble(self, ctx: Context) -> dict:
        s = ctx.source["settings"]
        p = ctx.source["package"]
        root_ark = ctx.extras["guid_map"]["root"]
        contributors = [c.get("title") or c.get("email") for c in (p.get("contributors") or [])]
        authors = [c.get("title") or c.get("email") for c in (p.get("contributors") or [])
                   if c.get("role") == "author"] or contributors
        licenses = p.get("licenses") or []
        first_license = licenses[0] if licenses else {}
        root = {
            "@id": root_ark,
            "@type": ["Dataset", EVI + "ROCrate"],
            "conformsTo": {"@id": "https://w3id.org/fairscape/profile/0.1"},
            "name": s["name"],
            "description": s["description"],
            "keywords": s["keywords"],
            "version": s["version"],
            "author": s["author"] or ", ".join(a for a in authors if a),
            "license": s["license"] or (first_license.get("path") or first_license.get("name")
                                        if isinstance(first_license, dict) else first_license),
            "datePublished": s["date_published"],
            "hasPart": [{"@id": i} for i in ctx.order],
        }
        if p.get("homepage"):
            root["url"] = p["homepage"]
        if p.get("id"):
            root["identifier"] = p["id"]
        if p.get("name"):
            root["alternateName"] = p["name"]
        crate = {
            "@context": DEFAULT_CONTEXT,
            "@graph": [
                {
                    "@id": "ro-crate-metadata.json",
                    "@type": "CreativeWork",
                    "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
                    "about": {"@id": root_ark},
                },
                root,
                *[ctx.out_nodes[i] for i in ctx.order],
            ],
        }
        if ctx.extras.get("validate"):
            from copy import deepcopy
            from fairscape_models.rocrate import ROCrateV1_2
            ROCrateV1_2.model_validate(deepcopy(crate))
        return crate

    def export(self, source, options: dict) -> dict:
        """EVI crate -> Data Package descriptor: bespoke driver composing
        ``apply_export_rules`` (see export_convert below)."""
        return export_convert(source, self, options)


# ============================================================================
# Export (EVI -> Data Package) — bespoke, composes apply_export_rules
# ============================================================================

def _kind(node) -> str:
    types = node.get("@type") or []
    types = types if isinstance(types, list) else [types]
    names = [str(t).split("#")[-1].split(":")[-1] for t in types]
    if "ROCrate" in names:
        return "ROCrate"
    for known in ("Schema", "Dataset", "Computation", "Software"):
        if known in names:
            return known
    return names[-1] if names else ""


def _is_descriptor_file(node) -> bool:
    name = str(node.get("name") or node.get("localPath") or "")
    return os.path.basename(name) in ("datapackage.json", "datapackage.yaml", "datapackage.yml")


def export_convert(crate: dict, plugin, options: dict) -> dict:
    """The crate's root becomes the package, every Dataset a resource, and a
    Dataset's ``evi:Schema`` its Table Schema. The crate's own descriptor
    Dataset (if it came from a package) is not a resource of the new one.
    Provenance nodes (Computation, Software) have no Data Package home and
    are left out."""
    graph = crate.get("@graph", [])
    root = next((n for n in graph if _kind(n) == "ROCrate"), None)
    if root is None:
        raise ValueError("no ROCrate root node in @graph")
    by_id = {n.get("@id"): n for n in graph}
    mapping = plugin.mapping

    ctx = Context(plugin, "export", crate)
    ctx.extras.update(options)
    package_license = root.get("license")
    ctx.extras["package_license"] = package_license

    resources = []
    for node in graph:
        if _kind(node) != "Dataset" or _is_descriptor_file(node):
            continue
        resource = apply_export_rules(node, mapping.export_rules_by_target("Dataset"), ctx)
        schema_ref = node.get("evi:Schema") or node.get("EVI:Schema") or node.get("schema")
        schema_id = schema_ref.get("@id") if isinstance(schema_ref, dict) else schema_ref
        schema_node = by_id.get(schema_id) if schema_id else None
        if schema_node and schema_node.get("properties"):
            table = apply_export_rules(schema_node, mapping.export_rules_by_target("Schema"), ctx)
            resource["schema"] = table
            separator = schema_node.get("separator")
            header = schema_node.get("header")
            dialect = {}
            if separator not in (None, ",", ""):
                dialect["delimiter"] = separator
            if header is False:
                dialect["header"] = False
            if dialect:
                resource["dialect"] = dialect
            resource["profile"] = "tabular-data-resource"
        # descriptor field order: identity first, then the rest as mapped
        ordered = {k: resource[k] for k in ("profile", "name", "path", "title", "description",
                                            "format", "mediatype", "bytes", "hash", "licenses",
                                            "sources", "dialect", "schema") if k in resource}
        ordered.update({k: v for k, v in resource.items() if k not in ordered})
        resources.append(ordered)

    seen = set()
    for r in resources:                       # resource names must be unique
        base, n = r["name"], 1
        while r["name"] in seen:
            n += 1
            r["name"] = f"{base}-{n}"
        seen.add(r["name"])

    authors = [a.strip() for a in str(root.get("author") or "").split(",") if a.strip()]
    package = {
        "profile": "tabular-data-package" if resources and all("schema" in r for r in resources)
                   else "data-package",
        "name": resource_slug(root.get("alternateName") or root.get("name")),
        "title": root.get("name"),
        "description": root.get("description"),
        "version": root.get("version"),
        "created": root.get("datePublished"),
        "homepage": root.get("url"),
        "id": root.get("identifier"),
        "keywords": root.get("keywords"),
        "licenses": [license_entry(package_license)] if package_license else None,
        "contributors": [{"title": a, "role": "author"} for a in authors] or None,
        "resources": resources,
    }
    return {k: v for k, v in package.items() if v not in (None, "", [])}


PLUGIN = FrictionlessPlugin()

EXTRACT_OPTIONS = ("naan", "name", "description", "author", "keywords", "license",
                   "version", "date_published", "crate_dir")


def convert(direction: str, source, **options):
    """Convert a Frictionless Data Package into an EVI RO-Crate (import only).

    ``source`` is a package directory, a ``datapackage.json`` path, a parsed
    descriptor (a dict with ``resources``), or the records dict
    ``extract()`` returns (a dict with ``settings``). Options ``name``,
    ``author``, ``keywords``, ``license``, ``description``, ``version``,
    ``naan``, ``date_published``, ``crate_dir`` override the package's own
    metadata; ``validate=True`` checks the crate against fairscape_models.
    """
    if direction == "import":
        is_records = isinstance(source, dict) and "settings" in source and "package" in source
        if not is_records:
            extract_opts = {k: options.pop(k) for k in list(options) if k in EXTRACT_OPTIONS}
            source = extract_records(source, **extract_opts)
    return PLUGIN.convert(direction, source, **options)
