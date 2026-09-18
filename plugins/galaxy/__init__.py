#!/usr/bin/env python3
"""galaxy plugin — a Galaxy invocation export (or a .ga workflow) -> EVI RO-Crate.

Galaxy can already write a Workflow Run RO-Crate, and the ``wrroc`` plugin
reads that. This plugin reads Galaxy's *own* export instead — the model
store every "export invocation" produces, in whatever container
(``.tar.gz``, ``.zip``, ``.rocrate.zip``, unpacked folder) — and so keeps
what the WRROC rendering drops: each job's parameters, command line, state
and exit code, tool versions and ToolShed origins, dataset hashes, and the
upload jobs that made the inputs.

    convert("import", "invocation-export.tar.gz")
    convert("import", "path/to/unpacked-export/")
    convert("import", "my_workflow.ga")                 # definition only: Software nodes
    convert("import", "https://usegalaxy.example", api_key=..., invocation_id=...)
    convert("import", records)                          # pre-extracted (extract.py)

The crate holds the invocation as a **Computation** (usedSoftware: the
workflow + Galaxy; usedDataset: its inputs; generated: its declared
outputs; parameters), one **Computation per job** (isPartOf the
invocation; usedSoftware: the tool; usedDataset / generated from Galaxy's
own input/output maps; the command line; flattened tool params), the
workflow, Galaxy and each distinct tool as **Software**, one **Dataset**
per underlying dataset (history copies of one file collapse onto one node,
keyed by dataset uuid) and one per dataset collection (hasPart: its
elements). Upload jobs stay outside the invocation but generate its inputs,
so the evidence graph reaches back to the raw files.

ARKs are deterministic (core.arks): run-scoped ones hash the invocation
uuid, tool ones hash ``tool_id@version``, dataset ones the dataset uuid —
so re-exporting the same invocation reproduces every identifier. Import
only.
"""

from __future__ import annotations

import os

from ...core import Context, PluginBase, Record, apply_import_rules
from ...core.arks import mint_ark
from .extract import extract as extract_records
from .parsers import IMPORT_PARSERS, tool_short_name

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


class GalaxyPlugin(PluginBase):
    name = "galaxy"
    import_parsers = IMPORT_PARSERS

    def pre(self, ctx: Context) -> None:
        """Mint every ARK and queue records in crate emission order (run,
        jobs, workflow, engine, tools, datasets, collections)."""
        src = ctx.source
        settings = src["settings"]
        naan = settings["naan"]
        inv = src.get("invocation")
        wf = src.get("workflow")
        title = settings["name"]

        run_key = (f"galaxy-invocation-{inv['uuid'] or inv['encoded_id']}" if inv
                   else f"galaxy-workflow-{(wf or {}).get('uuid') or title}")
        wf_key = f"galaxy-workflow-{(wf or {}).get('uuid') or title}"

        guid_map = {
            "root": mint_ark(naan, "rocrate", title, run_key),
            "workflow": mint_ark(naan, "software", (wf or {}).get("name") or title, wf_key),
            "engine": mint_ark(naan, "software", "galaxy",
                               "galaxy-" + str((inv or {}).get("galaxy_version") or "unversioned")),
        }
        if inv:
            guid_map["run"] = mint_ark(naan, "computation", title, run_key + "#run")
        for tool in src.get("tools", []):
            key = f"tool:{tool['tool_id']}@{tool['tool_version'] or ''}"
            guid_map[key] = mint_ark(naan, "software", tool_short_name(tool["tool_id"]),
                                     f"galaxy-tool-{tool['tool_id']}@{tool['tool_version'] or ''}")
        for job in src.get("jobs", []):
            guid_map["job:" + job["encoded_id"]] = mint_ark(
                naan, "computation", tool_short_name(job.get("tool_id")),
                run_key + "#job:" + job["encoded_id"])
        # datasets: every HDA of one underlying file shares one ARK
        copies: dict[str, list] = {}
        for d in src.get("datasets", []):
            copies.setdefault(d["key"], []).append(d)
        for key, group in copies.items():
            ark = mint_ark(naan, "dataset", group[0]["name"], f"galaxy-dataset-{key}")
            for d in group:
                guid_map["dataset:" + d["encoded_id"]] = ark
                for alias in d.get("copy_chain", []):     # the originals it was copied from
                    guid_map.setdefault("dataset:" + alias, ark)
        for c in src.get("collections", []):
            ark = mint_ark(naan, "dataset", c["name"], run_key + "#collection:" + c["encoded_id"])
            guid_map["collection:" + c["encoded_id"]] = ark
            for alias in c.get("copy_chain", []):
                guid_map.setdefault("collection:" + alias, ark)
        ctx.extras["guid_map"] = guid_map
        ctx.extras["copies"] = copies
        ctx.extras["by_collection"] = {c["encoded_id"]: c for c in src.get("collections", [])}

        # A job may name a dataset the export left out (deleted, or in
        # another history); those references are simply not edges.
        produced_by = {}
        for job in src.get("jobs", []):
            job_ark = guid_map["job:" + job["encoded_id"]]
            for d in job["outputs"]:
                if guid_map.get("dataset:" + d):
                    produced_by.setdefault(guid_map["dataset:" + d], job_ark)
            for c in job["output_collections"]:
                if guid_map.get("collection:" + c):
                    produced_by.setdefault(guid_map["collection:" + c], job_ark)
                for element in ctx.extras["by_collection"].get(c, {}).get("elements", []):
                    if element.get("dataset") and guid_map.get("dataset:" + element["dataset"]):
                        produced_by.setdefault(guid_map["dataset:" + element["dataset"]], job_ark)
        ctx.extras["produced_by"] = produced_by

        rule_for = {e.source_type: e for e in ctx.mapping.entities}
        records = []
        if inv:
            records.append(Record(inv, rule_for["run"], "run"))
        records += [Record(j, rule_for["job"], "job:" + j["encoded_id"]) for j in src.get("jobs", [])]
        if wf:
            records.append(Record(wf, rule_for["workflow"], "workflow"))
        records.append(Record({"version": (inv or {}).get("galaxy_version") or ""},
                              rule_for["engine"], "engine"))
        records += [Record(t, rule_for["tool"], f"tool:{t['tool_id']}@{t['tool_version'] or ''}")
                    for t in src.get("tools", [])]
        seen = set()
        for d in src.get("datasets", []):
            if d["key"] in seen:
                continue                      # one node per underlying file
            seen.add(d["key"])
            records.append(Record(d, rule_for["dataset"], "dataset:" + d["encoded_id"]))
        records += [Record(c, rule_for["collection"], "collection:" + c["encoded_id"])
                    for c in src.get("collections", [])]
        ctx.records = records

    def select_rules(self, ctx: Context, rec: Record):
        return ctx.mapping.import_rules_by_source(rec.rule.source_type)

    def map_record(self, ctx: Context, rec: Record, rules):
        node = {"@id": ctx.extras["guid_map"][rec.source_id],
                "@type": list(rec.rule.target_type_iri)}
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
            "author": s["author"] or "Unknown",
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
            "galaxy is import-only: a crate cannot be turned back into a Galaxy invocation")


PLUGIN = GalaxyPlugin()

EXTRACT_OPTIONS = ("api_key", "invocation_id", "naan", "name", "description", "author",
                   "keywords", "license", "version", "date_published", "crate_dir")


def convert(direction: str, source, **options):
    """Convert a Galaxy export into an EVI RO-Crate (import only).

    ``source`` is an invocation export archive or folder, a ``.ga`` file, a
    Galaxy URL (with ``api_key=`` and ``invocation_id=``), or the records
    dict ``extract()`` returns. ``validate=True`` checks the crate against
    fairscape_models.
    """
    if direction == "import" and isinstance(source, (str, os.PathLike)):
        extract_opts = {k: options.pop(k) for k in list(options) if k in EXTRACT_OPTIONS}
        source = extract_records(source, **extract_opts)
    return PLUGIN.convert(direction, source, **options)
