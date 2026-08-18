#!/usr/bin/env python3
"""snakemake plugin — Snakemake run records -> FAIRSCAPE EVI RO-Crate.

The source document is the plain-data extraction that
``snakemake-report-plugin-fairscape`` performs against Snakemake's report
interface and persistence metadata (the report plugin owns all Snakemake and
filesystem I/O; this plugin owns the conversion):

    {
      "settings":    {naan, name, description, author, keywords, license,
                      version, date_published},
      "run":         {name, snakefile, snakefile_key, engine_version,
                      starttime, endtime},
      "jobs":        [{rule, wildcards, shellcmd, params, inputs, outputs,
                       starttime, endtime, container_img_url, conda_env}, ...],
      "rules":       {name: {source, language, container_img_url, conda_env,
                             definition_kind, definition_ref}},
      "files":       {path: {size, locator, locator_value, is_dir, parent}},
      "configfiles": [path, ...],
      "schemas":     {path: <pre-built EVI Schema node>}
    }

The emitted crate mirrors nf-fairscape's (docs/FAIRSCAPE.md there): descriptor
-> root ["Dataset", EVI#ROCrate] -> run Computation -> job Computations ->
Software (Snakefile + engine + one per rule) -> Datasets -> Schema nodes.
ARKs are deterministic (core.arks): they hash run-independent strings, so
re-running the report — or the whole workflow — reproduces the identifiers.
"""

from __future__ import annotations

import os

from ...core import Context, PluginBase, Record, apply_import_rules
from ...core.arks import mint_ark
from .parsers import (IMPORT_PARSERS, job_ark_source, job_display_name, refs)

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
    "annotates": {"@id": EVI + "annotates", "@type": "@id"},
    "hasDistribution": {"@id": EVI + "hasDistribution", "@type": "@id"},
    "localPath": "https://w3id.org/ro/terms#localPath",
}


class SnakemakePlugin(PluginBase):
    name = "snakemake"
    import_parsers = IMPORT_PARSERS

    def pre(self, ctx: Context) -> None:
        """Index the run records, mint every ARK, and queue records in crate
        emission order (run, jobs, workflow, engine, rules, files, schemas)."""
        src = ctx.source
        settings = src["settings"]
        run = src["run"]
        jobs = src.get("jobs", [])
        rules = src.get("rules", {})
        files = src.get("files", {})
        naan = settings["naan"]

        ctx.extras["settings"] = settings
        ctx.extras["run"] = run
        ctx.extras["configfiles"] = set(src.get("configfiles", []))
        ctx.extras["schemas"] = src.get("schemas", {})

        key = run["snakefile_key"]
        guid_map = {
            "root": mint_ark(naan, "rocrate", run["name"], key),
            "run": mint_ark(naan, "computation", run["name"], key + "#run"),
            "workflow": mint_ark(naan, "software",
                                 os.path.basename(run["snakefile"]), key),
            "engine": mint_ark(naan, "software", "snakemake",
                               "snakemake-" + run["engine_version"]),
        }
        for i, job in enumerate(jobs):
            guid_map[f"job:{i}"] = mint_ark(
                naan, "computation", job_display_name(job), job_ark_source(job))
        for rule_name in rules:
            guid_map[f"rule:{rule_name}"] = mint_ark(
                naan, "software", rule_name, key + "#" + rule_name)
        for path in files:
            guid_map[f"file:{path}"] = mint_ark(
                naan, "dataset", os.path.basename(path), os.path.normpath(path))
        ctx.extras["guid_map"] = guid_map

        produced_by = {}
        consumed = set()
        for i, job in enumerate(jobs):
            for out in job["outputs"]:
                produced_by[os.path.normpath(out)] = guid_map[f"job:{i}"]
            for inp in job["inputs"]:
                consumed.add(os.path.normpath(inp))
        ctx.extras["produced_by"] = produced_by

        all_paths = sorted(files)
        ctx.extras["root_inputs"] = [
            p for p in all_paths
            if os.path.normpath(p) not in produced_by
            and p not in ctx.extras["configfiles"]
            and not files[p].get("parent")]
        ctx.extras["terminal_outputs"] = [
            p for p in all_paths
            if os.path.normpath(p) in produced_by
            and os.path.normpath(p) not in consumed]

        rule_for = {e.source_type: e for e in ctx.mapping.entities}
        records = [Record(run, rule_for["run"], "run")]
        records += [Record(job, rule_for["job"], f"job:{i}")
                    for i, job in enumerate(jobs)]
        records.append(Record(run, rule_for["workflow"], "workflow"))
        records.append(Record(run, rule_for["engine"], "engine"))
        records += [Record({"name": n, **(rules[n] or {})}, rule_for["rule"], f"rule:{n}")
                    for n in sorted(rules)]
        records += [Record({"path": p, **files[p]}, rule_for["file"], f"file:{p}")
                    for p in all_paths]
        records += [Record(ctx.extras["schemas"][p], rule_for["schema"], f"schema:{p}")
                    for p in sorted(ctx.extras["schemas"])]
        ctx.records = records

    def select_rules(self, ctx: Context, rec: Record):
        """Rules key on the SOURCE type here — run and job both map to
        Computation but with different rule sets."""
        return ctx.mapping.import_rules_by_source(rec.rule.source_type)

    def map_record(self, ctx: Context, rec: Record, rules):
        if rec.rule.source_type == "schema":
            return dict(rec.data)          # pre-built node, passes through
        node = {
            "@id": ctx.extras["guid_map"][rec.source_id],
            "@type": list(rec.rule.target_type_iri),
        }
        node.update(apply_import_rules(rec.data, rules, ctx))
        return node

    def assemble(self, ctx: Context) -> dict:
        s = ctx.extras["settings"]
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
            "hasPart": refs(list(ctx.order)),
        }
        return {
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


    def export(self, source, options: dict):
        raise NotImplementedError(
            "snakemake is import-only: a crate cannot be turned back into a "
            "Snakemake run")


PLUGIN = SnakemakePlugin()


def convert(direction: str, source: dict, **options):
    return PLUGIN.convert(direction, source, **options)
