#!/usr/bin/env python3
"""redcap plugin — a REDCap project's exports -> FAIRSCAPE EVI RO-Crate.

REDCap (Research Electronic Data Capture) is where most clinical and public
health survey data starts. A project's metadata lives in its *data
dictionary* — one row per field: name, form, type, label, choices,
validation, min/max, the PHI "Identifier?" flag, branching logic, required.
That is a codebook, and a codebook is an EVI tabular Schema. This plugin:

    convert("import", "MyStudy_DataDictionary_2026-01-12.csv")
    convert("import", "dictionary.csv", records="MyStudy_DATA_2026-01-12_1530.csv")
    convert("import", "metadata.json")           # the API's content=metadata export
    convert("import", records)                    # pre-extracted (extract.py) records

produces a crate holding:

* one **Schema** describing the columns of a *record export* of the project
  (the columns, not the fields: checkboxes expand to ``field___code``, each
  form gains ``<form>_complete``, descriptive fields vanish). Each column
  keeps the REDCap facts a codebook reader wants — form, field type, choice
  codes and labels, validation, branching logic, and ``phiIdentifier``
  where REDCap flags the field as an identifier;
* a **Dataset** for the dictionary file, and one for the records export if
  given, the latter carrying ``evi:Schema`` -> the Schema above. When a
  records export is given its header decides which columns the Schema
  lists and in what order, so a de-identified export (identifier fields
  removed) gets a Schema that matches the file, and a longitudinal one
  gets its ``redcap_event_name`` column;
* a **Computation** (the export) that ``used`` REDCap (a **Software** node)
  and ``generated`` the files.

ARKs are deterministic (core.arks): they hash what the dictionary defines
(field names, forms, types, validations, choices), so re-downloading an
unchanged project reproduces the identifiers, and relabelling a field does
not re-mint them. Import only: a crate cannot become a REDCap project.

Superseded: github.com/fairscape/REDCapDataDictionaryConverter (2024), a
one-class script that emitted a bare Schema JSON with no crate, no
checkbox expansion, no form status columns and no PHI flags.
"""

from __future__ import annotations

import os

from ...core import Context, PluginBase, Record, apply_import_rules
from ...core.arks import mint_ark
from .extract import extract as extract_records
from .parsers import IMPORT_PARSERS

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


class RedcapPlugin(PluginBase):
    name = "redcap"
    import_parsers = IMPORT_PARSERS

    def pre(self, ctx: Context) -> None:
        """Mint every ARK from the dictionary digest and queue the records in
        crate emission order (schema, dictionary file, records file, export,
        REDCap)."""
        src = ctx.source
        settings = src["settings"]
        project = src["project"]
        naan = settings["naan"]
        key = project["dictionary_key"]
        name = project["name"]

        guid_map = {
            "root": mint_ark(naan, "rocrate", name, key),
            "project": mint_ark(naan, "schema", name, key + "#schema"),
            "dictionary": mint_ark(naan, "dataset", src["dictionary_file"]["file"],
                                   key + "#dictionary"),
            "export": mint_ark(naan, "computation", "redcap-export-" + name, key + "#export"),
            "redcap": mint_ark(naan, "software", "redcap",
                               "redcap-" + (project.get("redcap_version") or "unversioned")),
        }
        if src.get("records"):
            guid_map["records"] = mint_ark(naan, "dataset", src["records"]["file"],
                                           key + "#records:" + src["records"]["file"])
        ctx.extras["guid_map"] = guid_map

        rule_for = {e.source_type: e for e in ctx.mapping.entities}
        records = [
            Record(project, rule_for["project"], "project"),
            Record(src["dictionary_file"], rule_for["dictionary"], "dictionary"),
        ]
        if src.get("records"):
            records.append(Record(src["records"], rule_for["records"], "records"))
        records.append(Record({}, rule_for["export"], "export"))
        records.append(Record({"version": project.get("redcap_version") or ""},
                              rule_for["redcap"], "redcap"))
        ctx.records = records

    def select_rules(self, ctx: Context, rec: Record):
        """Rules key on the SOURCE type: two source types map to Dataset."""
        return ctx.mapping.import_rules_by_source(rec.rule.source_type)

    def map_record(self, ctx: Context, rec: Record, rules):
        node = {"@id": ctx.extras["guid_map"][rec.source_id]}
        if rec.rule.source_type == "project":
            node["@context"] = SCHEMA_CONTEXT
        iri = list(rec.rule.target_type_iri)
        node["@type"] = iri if len(iri) > 1 else iri[0]
        node.update(apply_import_rules(rec.data, rules, ctx))
        return node

    def assemble(self, ctx: Context) -> dict:
        s = ctx.source["settings"]
        root_ark = ctx.extras["guid_map"]["root"]
        root = {
            "@id": root_ark,
            "@type": ["Dataset", EVI + "ROCrate"],
            "conformsTo": {"@id": "https://w3id.org/fairscape/profile/0.1"},
            "name": s["name"],
            "description": s["description"],
            "keywords": s["keywords"],
            "version": s["version"],
            "author": s["author"],
            "license": s["license"],
            "datePublished": s["date_published"],
            "hasPart": [{"@id": i} for i in ctx.order],
        }
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

    def export(self, source, options: dict):
        raise NotImplementedError(
            "redcap is import-only: a crate cannot be turned back into a REDCap project")


PLUGIN = RedcapPlugin()

#: ``convert`` options that belong to extraction, not to the mapping.
EXTRACT_OPTIONS = ("records", "naan", "name", "description", "author", "keywords",
                   "license", "version", "date_published", "redcap_version",
                   "labels", "crate_dir")


def convert(direction: str, source, **options):
    """Convert a REDCap project's exports into an EVI RO-Crate (import only).

    ``source`` is either the data dictionary path — a CSV download or the
    API's metadata JSON; pass ``records=`` for the record export CSV and any
    of ``name``, ``author``, ``keywords``, ``license``, ``description``,
    ``naan``, ``date_published``, ``redcap_version``, ``labels``,
    ``crate_dir`` — or the plain records dict ``extract()`` returns.
    ``validate=True`` checks the crate against fairscape_models.
    """
    if direction == "import" and isinstance(source, (str, os.PathLike)):
        extract_opts = {k: options.pop(k) for k in list(options) if k in EXTRACT_OPTIONS}
        source = extract_records(source, **extract_opts)
    return PLUGIN.convert(direction, source, **options)
