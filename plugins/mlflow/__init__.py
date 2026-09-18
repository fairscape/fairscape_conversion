#!/usr/bin/env python3
"""mlflow plugin — MLflow tracking store -> FAIRSCAPE EVI RO-Crate.

Import-only and self-contained, like cromwell: MLflow has no run-completion
hook (its plugin points are stores and context providers, none of which fire
when a run ends), so this is a post-hoc exporter — ``extract.py`` walks a
finished experiment/run through the ``MlflowClient`` read API into plain
records, and this plugin owns the conversion:

    convert("import", "path/to/mlruns", experiment="iris")  # extract + convert
    convert("import", "sqlite:///mlflow.db", run_id="...")  # any tracking URI
    convert("import", records)                              # pre-extracted
                                                            # (the golden test)

    {
      "settings":   {naan, name, description, author, keywords, license,
                     version, date_published},
      "experiment": {name, experiment_id, ark_source},
      "engine":     {version},
      "runs":       [{run_id, name, parent_run_id, status, user, source_key,
                      start_time, end_time, params, metrics, tags, container,
                      dataset_inputs, model_inputs, artifacts, models}, ...],
      "sources":    {key: {name, source_type, git_commit, ark_source}},
      "datasets":   {key: {name, digest, source_type, source_uri, columns,
                           num_rows, contexts, ark_source}},
      "models":     {model_id: {name, run_id, flavor, mlflow_version, size,
                                locator, locator_value, ark_source}},
      "files":      {key: {path, run_id, size, locator, locator_value,
                           ark_source}},
      "schemas":    {"dataset:<key>"|"file:<key>": <EVI Schema node>}
    }
"""

from __future__ import annotations

import os

from ...core import Context, PluginBase, Record, apply_import_rules
from ...core.arks import mint_ark
from .extract import extract
from .parsers import IMPORT_PARSERS, file_display_name, refs

EVI = "https://w3id.org/EVI#"

DEFAULT_CONTEXT = {
    "@vocab": "https://schema.org/",
    "evi": "https://w3id.org/EVI#",
    "rai": "http://mlcommons.org/croissant/RAI/",
    "prov": "http://www.w3.org/ns/prov#",
    "mls": "http://www.w3.org/ns/mls#",
    "usedSoftware": {"@id": EVI + "usedSoftware", "@type": "@id"},
    "usedDataset": {"@id": EVI + "usedDataset", "@type": "@id"},
    "usedMLModel": {"@id": EVI + "usedMLModel", "@type": "@id"},
    "generatedBy": {"@id": EVI + "generatedBy", "@type": "@id"},
    "generated": {"@id": EVI + "generated", "@type": "@id"},
    "annotates": {"@id": EVI + "annotates", "@type": "@id"},
    "hasDistribution": {"@id": EVI + "hasDistribution", "@type": "@id"},
    "localPath": "https://w3id.org/ro/terms#localPath",
}


class MlflowPlugin(PluginBase):
    name = "mlflow"
    import_parsers = IMPORT_PARSERS

    def pre(self, ctx: Context) -> None:
        """Index the records, mint every ARK, and queue records in crate
        emission order (runs, sources, engine, datasets, models, files,
        schemas). Models are EVI MLModel nodes; their ARKs keep the
        ``dataset-`` prefix they have always had."""
        src = ctx.source
        settings = src["settings"]
        experiment = src["experiment"]
        engine = src["engine"]
        runs = src.get("runs", [])
        sources = src.get("sources", {})
        datasets = src.get("datasets", {})
        models = src.get("models", {})
        files = src.get("files", {})
        naan = settings["naan"]

        ctx.extras["settings"] = settings
        ctx.extras["experiment"] = experiment
        ctx.extras["sources"] = sources
        ctx.extras["schemas"] = src.get("schemas", {})
        ctx.extras["runs_by_id"] = {r["run_id"]: r for r in runs}

        guid_map = {
            "root": mint_ark(naan, "rocrate", settings["name"],
                             experiment["ark_source"]),
            "engine": mint_ark(naan, "software", "mlflow",
                               "mlflow-" + engine["version"]),
        }
        for run in runs:
            guid_map[f"run:{run['run_id']}"] = mint_ark(
                naan, "computation", run["name"], run["ark_source"])
        for key in sources:
            guid_map[f"source:{key}"] = mint_ark(
                naan, "software", file_display_name(sources[key]["name"]),
                sources[key]["ark_source"])
        for key in datasets:
            guid_map[f"dataset:{key}"] = mint_ark(
                naan, "dataset", datasets[key]["name"],
                datasets[key]["ark_source"])
        for mid in models:
            guid_map[f"model:{mid}"] = mint_ark(
                naan, "dataset", models[mid]["name"],
                models[mid]["ark_source"])
        for key in files:
            guid_map[f"file:{key}"] = mint_ark(
                naan, "dataset", file_display_name(files[key]["path"]),
                files[key]["ark_source"])
        ctx.extras["guid_map"] = guid_map

        rule_for = {e.source_type: e for e in ctx.mapping.entities}
        records = [Record(run, rule_for["run"], f"run:{run['run_id']}")
                   for run in runs]
        records += [Record(sources[k], rule_for["source"], f"source:{k}")
                    for k in sorted(sources)]
        records.append(Record(engine, rule_for["engine"], "engine"))
        records += [Record(datasets[k], rule_for["dataset"], f"dataset:{k}")
                    for k in sorted(datasets)]
        records += [Record(models[m], rule_for["model"], f"model:{m}")
                    for m in sorted(models)]
        records += [Record(files[k], rule_for["file"], f"file:{k}")
                    for k in sorted(files)]
        records += [Record(ctx.extras["schemas"][k], rule_for["schema"],
                           f"schema:{k}")
                    for k in sorted(ctx.extras["schemas"])]
        ctx.records = records

    def select_rules(self, ctx: Context, rec: Record):
        """Rules key on the SOURCE type here — run maps to Computation while
        dataset/model/file all map to Dataset with different rule sets."""
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
            "mlflow is import-only: a crate cannot be turned back into "
            "MLflow runs")


PLUGIN = MlflowPlugin()


def convert(direction: str, source, **options):
    """Convert MLflow runs into an EVI RO-Crate (import only).

    ``source`` is either an MLflow tracking URI / mlruns directory path
    (extraction options — experiment, run_id, crate_dir, naan, name, author,
    date_published, copy_artifacts, schemas … — pass through as keyword
    arguments) or an already-extracted records dict.
    """
    if direction == "import" and isinstance(source, (str, os.PathLike)):
        linking = {k: options.pop(k) for k in ("linked_crates", "link_report")
                   if k in options}
        if "crate_dir" in options:
            linking["crate_dir"] = options["crate_dir"]
        source = extract(source, **options)
        options = linking
    return PLUGIN.convert(direction, source, **options)
