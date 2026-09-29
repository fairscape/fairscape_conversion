#!/usr/bin/env python3
"""python plugin — a tracked Python run -> FAIRSCAPE EVI RO-Crate.

Unlike the other importers there is no upstream tool whose output this reads:
``record.py`` runs the code itself (a script, or a Jupyter cell) and writes
down the files it read and wrote, and ``track.py`` drives record -> convert ->
merge into a crate directory. This module is the pure conversion of that run
record:

    {
      "settings": {naan, name, description, author, keywords, license,
                   version, date_published},
      "run":      {name, script: {name, locator, locator_value}, code_sha1,
                   argv, python_version, starttime, endtime, exit_code},
      "files":    {abs_path: {role: input|output, size, locator, locator_value}}
    }

The crate is descriptor -> root -> one Computation -> the Software it ran ->
one Dataset per file. ARKs are deterministic (core.arks): the Software hashes
the code (identical code is one Software across runs), an input hashes its
path, and the Computation and its outputs hash in the start time, since
re-running writes new versions of the outputs.

    from fairscape_conversion.plugins import python as pyrun
    crate = pyrun.convert("import", record)

    python -m fairscape_conversion.core.cli track analysis.py -- --epochs 3
"""

from __future__ import annotations

import os

from ...core import Context, PluginBase, Record, apply_import_rules
from ...core.arks import mint_ark
from .parsers import IMPORT_PARSERS, refs

EVI = "https://w3id.org/EVI#"

DEFAULT_CONTEXT = {
    "@vocab": "https://schema.org/",
    "evi": "https://w3id.org/EVI#",
    "prov": "http://www.w3.org/ns/prov#",
    "usedSoftware": {"@id": EVI + "usedSoftware", "@type": "@id"},
    "usedDataset": {"@id": EVI + "usedDataset", "@type": "@id"},
    "generatedBy": {"@id": EVI + "generatedBy", "@type": "@id"},
    "generated": {"@id": EVI + "generated", "@type": "@id"},
    "localPath": "https://w3id.org/ro/terms#localPath",
}


def run_key(run: dict) -> str:
    """The string a run's run-scoped ARKs hash: which code, and when."""
    return f"{run['script']['locator_value']}#{run['starttime']}"


class PythonPlugin(PluginBase):
    name = "python"
    import_parsers = IMPORT_PARSERS

    def pre(self, ctx: Context) -> None:
        src = ctx.source
        settings = src["settings"]
        run = src["run"]
        files = src.get("files", {})
        naan = settings["naan"]

        ctx.extras["settings"] = settings
        ctx.extras["run"] = run
        ctx.extras["files"] = files

        key = run_key(run)
        guid_map = {
            "root": mint_ark(naan, "rocrate", settings["name"], key),
            "run": mint_ark(naan, "computation", run["name"], key),
            "software": mint_ark(naan, "software", run["name"], run["code_sha1"]),
        }
        for path, info in files.items():
            source = os.path.normpath(path)
            if info["role"] == "output":
                source += "#" + run["starttime"]
            guid_map[f"file:{path}"] = mint_ark(
                naan, "dataset", os.path.basename(path), source)
        ctx.extras["guid_map"] = guid_map

        rule_for = {e.source_type: e for e in ctx.mapping.entities}
        records = [Record(run, rule_for["run"], "run"),
                   Record(run, rule_for["software"], "software")]
        records += [Record({"path": p, **files[p]}, rule_for["file"], f"file:{p}")
                    for p in sorted(files)]
        ctx.records = records

    def select_rules(self, ctx: Context, rec: Record):
        return ctx.mapping.import_rules_by_source(rec.rule.source_type)

    def map_record(self, ctx: Context, rec: Record, rules):
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
            "python is import-only: a crate cannot be turned back into a run")


PLUGIN = PythonPlugin()


def convert(direction: str, source: dict, **options):
    return PLUGIN.convert(direction, source, **options)


def load_ipython_extension(ipython):
    """``%load_ext fairscape_conversion.plugins.python`` registers ``%%fairscape``."""
    from .magic import load_ipython_extension as _load
    _load(ipython)
