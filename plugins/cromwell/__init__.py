#!/usr/bin/env python3
"""cromwell plugin — Cromwell run metadata -> FAIRSCAPE EVI RO-Crate.

Import-only and self-contained, like c2m2: Cromwell writes everything the
crate needs into one metadata JSON (``cromwell run -m metadata.json``, or a
server's ``GET /api/workflows/v1/{id}/metadata`` response), so there is no
engine-process integration — ``extract.py`` reads that file (plus the disk,
for sizes/locators) into plain records, and this plugin owns the conversion:

    convert("import", "path/to/metadata.json")   # extract + convert
    convert("import", records)                   # pre-extracted records
                                                 # (what the golden test feeds)

    {
      "settings":    {naan, name, description, author, keywords, license,
                      version, date_published},
      "run":         {name, workflow_name, wdl_ref, wdl_key, language,
                      engine_version, workflow_id, command, status,
                      starttime, endtime},
      "jobs":        [{task, shard, attempt, shellcmd, parameters, inputs,
                       outputs, starttime, endtime, container, status}, ...],
      "tasks":       {name: {source, container}},
      "files":       {path: {size, locator, locator_value, ark_source,
                             is_config}},
      "run_outputs": [path, ...],
      "schemas":     {path: <pre-built EVI Schema node>}   # optional
    }

The emitted crate mirrors nf-fairscape's and plugins/snakemake's: descriptor
-> root ["Dataset", EVI#ROCrate] -> run Computation -> call Computations ->
Software (WDL + engine + one per task) -> Datasets -> Schema nodes. ARKs are deterministic
(core.arks): every hashed string is run-independent (``extract`` strips the
run-UUID directory from paths under workflowRoot), so re-running the same
workflow — a fresh Cromwell run, new UUID and all — reproduces the
identifiers. The standalone ``nf/cromwell-fairscape`` converter is the parity
reference (tests/test_cromwell.py).
"""

from __future__ import annotations

import os

from ...core import Context, PluginBase, Record, apply_import_rules
from ...core.arks import mint_ark
from .extract import extract
from .parsers import (IMPORT_PARSERS, job_display_name, refs)

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


def job_ark_source(job, files, wdl_key):
    return (wdl_key + "#" + job["task"]
            + "\0" + str(job["shard"])
            + "\0" + "\0".join(sorted(files[p]["ark_source"]
                                      for p in job["outputs"])))


class CromwellPlugin(PluginBase):
    name = "cromwell"
    import_parsers = IMPORT_PARSERS

    def pre(self, ctx: Context) -> None:
        """Index the run records, mint every ARK, and queue records in crate
        emission order (run, jobs, workflow, engine, tasks, files, schemas)."""
        src = ctx.source
        settings = src["settings"]
        run = src["run"]
        jobs = src.get("jobs", [])
        tasks = src.get("tasks", {})
        files = src.get("files", {})
        naan = settings["naan"]

        ctx.extras["settings"] = settings
        ctx.extras["run"] = run
        ctx.extras["run_outputs"] = src.get("run_outputs", [])
        ctx.extras["schemas"] = src.get("schemas", {})

        key = run["wdl_key"]
        guid_map = {
            "root": mint_ark(naan, "rocrate", run["name"], key),
            "run": mint_ark(naan, "computation", run["name"], key + "#run"),
            "workflow": mint_ark(naan, "software",
                                 os.path.basename(run["wdl_ref"]), key),
            "engine": mint_ark(naan, "software", "cromwell",
                               "cromwell-" + run["engine_version"]),
        }
        for i, job in enumerate(jobs):
            guid_map[f"job:{i}"] = mint_ark(
                naan, "computation", job_display_name(job),
                job_ark_source(job, files, key))
        for task_name in tasks:
            guid_map[f"task:{task_name}"] = mint_ark(
                naan, "software", task_name, key + "#" + task_name)
        for path in files:
            guid_map[f"file:{path}"] = mint_ark(
                naan, "dataset",
                os.path.basename(path.rstrip("/")) or path,
                files[path]["ark_source"])
        ctx.extras["guid_map"] = guid_map

        # call inputs hold pre-localization source paths, so producer ->
        # consumer linking is exact string matching on the metadata's paths
        produced_by = {}
        for i, job in enumerate(jobs):
            for out in job["outputs"]:
                produced_by[out] = guid_map[f"job:{i}"]
        ctx.extras["produced_by"] = produced_by

        all_paths = sorted(files)
        ctx.extras["root_inputs"] = [
            p for p in all_paths
            if p not in produced_by and not files[p]["is_config"]]

        rule_for = {e.source_type: e for e in ctx.mapping.entities}
        records = [Record(run, rule_for["run"], "run")]
        records += [Record(job, rule_for["job"], f"job:{i}")
                    for i, job in enumerate(jobs)]
        records.append(Record(run, rule_for["workflow"], "workflow"))
        records.append(Record(run, rule_for["engine"], "engine"))
        records += [Record({"name": n, **(tasks[n] or {})}, rule_for["task"], f"task:{n}")
                    for n in sorted(tasks)]
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
            "cromwell is import-only: a crate cannot be turned back into a "
            "Cromwell run")


PLUGIN = CromwellPlugin()


def convert(direction: str, source, **options):
    """Convert Cromwell run metadata into an EVI RO-Crate (import only).

    ``source`` is either a path to a Cromwell metadata JSON file (extraction
    options — crate_dir, naan, name, author, date_published, schemas … — pass
    through as keyword arguments) or an already-extracted records dict.
    """
    if direction == "import" and isinstance(source, (str, os.PathLike)):
        linking = {k: options.pop(k) for k in ("linked_crates", "link_report")
                   if k in options}
        if "crate_dir" in options:
            linking["crate_dir"] = options["crate_dir"]
        source = extract(source, **options)
        options = linking
    return PLUGIN.convert(direction, source, **options)
