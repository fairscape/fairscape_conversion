"""snakemake plugin parsers — the algorithm half of the mapping.

Every parser has the kernel signature ``fn(value, rule, ctx) -> value | None``
(``None`` = set nothing). The conversion state they read (``guid_map``,
``produced_by``, ``settings`` …) is computed once in the plugin's ``pre`` and
stashed in ``ctx.extras``.
"""

from __future__ import annotations

import os

from ...core.parsers import encoding_format_of, scalar


# ---- plain helpers (shared with the plugin's pre/assemble) -----------------




def ensure_description(text, fallback):
    text = (text or "").strip()
    if len(text) >= 10:
        return text
    return fallback


def ref(ark):
    return {"@id": ark}


def refs(arks):
    return [{"@id": a} for a in arks]


def job_display_name(job):
    if job.get("wildcards"):
        wc = ", ".join(f"{k}={v}" for k, v in sorted(job["wildcards"].items()))
        return f"{job['rule']} ({wc})"
    return job["rule"]


def job_ark_source(job):
    return job["rule"] + "\0" + "\0".join(sorted(job["outputs"]))


# ---- run --------------------------------------------------------------------

def run_name(value, rule, ctx):
    return f"Snakemake workflow run of '{os.path.basename(value)}'"


def run_description(value, rule, ctx):
    return (f"Execution of the Snakemake workflow '{os.path.basename(value)}', "
            "reconstructed post-hoc from Snakemake's persistence metadata "
            "by snakemake-report-plugin-fairscape")


def run_used_software(value, rule, ctx):
    g = ctx.extras["guid_map"]
    return refs([g["workflow"], g["engine"]])


def run_used_datasets(value, rule, ctx):
    g = ctx.extras["guid_map"]
    return refs([g[f"file:{p}"] for p in ctx.extras["root_inputs"]])


def run_generated(value, rule, ctx):
    g = ctx.extras["guid_map"]
    return refs([g[f"file:{p}"] for p in ctx.extras["terminal_outputs"]])


# ---- job --------------------------------------------------------------------

def job_name(value, rule, ctx):
    return job_display_name(ctx.node)


def job_description(value, rule, ctx):
    job = ctx.node
    return (f"Snakemake job for rule '{job['rule']}'"
            + (f" with wildcards {job['wildcards']}" if job.get("wildcards") else ""))


def rule_ref(value, rule, ctx):
    return refs([ctx.extras["guid_map"][f"rule:{value}"]])


def dataset_refs(value, rule, ctx):
    g = ctx.extras["guid_map"]
    return refs([g[f"file:{p}"] for p in (value or [])])


def run_ref(value, rule, ctx):
    return refs([ctx.extras["guid_map"]["run"]])


def param_strings(value, rule, ctx):
    if not value:
        return None
    return [str(p) for p in value]


# ---- shared field sources ---------------------------------------------------

def settings_author(value, rule, ctx):
    return ctx.extras["settings"]["author"]


def settings_date(value, rule, ctx):
    return ctx.extras["settings"]["date_published"]


def settings_keywords(value, rule, ctx):
    return ctx.extras["settings"]["keywords"]


def date_or_published(value, rule, ctx):
    return value or ctx.extras["settings"]["date_published"]


def basename(value, rule, ctx):
    return os.path.basename(value)


# ---- workflow / rule Software ----------------------------------------------

def workflow_description(value, rule, ctx):
    return f"Snakemake workflow definition '{os.path.basename(value)}' for this run"


def rule_description(value, rule, ctx):
    info = ctx.node
    return ensure_description(
        value,
        f"Snakemake rule '{info['name']}' from '{ctx.extras['run']['snakefile']}'")


def rule_format(value, rule, ctx):
    info = ctx.node
    if info.get("definition_ref"):
        return info.get("language") or "snakemake"
    return "snakemake"


def rule_content_url(value, rule, ctx):
    info = ctx.node
    return info.get("definition_ref") or ctx.extras["run"]["snakefile"]


def workflow_ref(value, rule, ctx):
    return refs([ctx.extras["guid_map"]["workflow"]])


# ---- file Datasets ----------------------------------------------------------

def file_description(value, rule, ctx):
    info = ctx.node
    path = info["path"]
    parent = info.get("parent")
    producer = ctx.extras["produced_by"].get(os.path.normpath(path))
    if parent:
        return (f"File '{path}' inside the directory output "
                f"'{parent}' of the Snakemake workflow run")
    if path in ctx.extras["configfiles"]:
        return f"Snakemake configuration file '{path}' for this run"
    if producer:
        kind = "Directory" if info.get("is_dir") else "File"
        return f"{kind} '{path}' produced by the Snakemake workflow run"
    return f"Input file '{path}' used by the Snakemake workflow run"


def encoding_format(value, rule, ctx):
    return encoding_format_of(value)


def file_generated_by(value, rule, ctx):
    info = ctx.node
    parent = info.get("parent")
    key = os.path.normpath(parent) if parent else os.path.normpath(value)
    producer = ctx.extras["produced_by"].get(key)
    return refs([producer]) if producer else []


def file_is_part_of(value, rule, ctx):
    info = ctx.node
    g = ctx.extras["guid_map"]
    if info.get("parent"):
        return refs([g[f"file:{info['parent']}"]])
    if value in ctx.extras["configfiles"]:
        return refs([g["workflow"]])
    return None


def file_schema_ref(value, rule, ctx):
    schema = ctx.extras["schemas"].get(value)
    return ref(schema["@id"]) if schema else None


def file_content_url(value, rule, ctx):
    info = ctx.node
    if info["locator"] == "contentUrl":
        return info["locator_value"]
    return None


def file_local_path(value, rule, ctx):
    info = ctx.node
    if info["locator"] == "localPath":
        return info["locator_value"]
    return None


def size_string(value, rule, ctx):
    return str(value) if value is not None else None


def csv_constant(value, rule, ctx):
    """Emit the rule's constant_value verbatim (the pattern the other plugins
    use for constants: a named parser reading rule.constant_value)."""
    return rule.constant_value


IMPORT_PARSERS = {
    "scalar": scalar,
    "run_name": run_name,
    "run_description": run_description,
    "run_used_software": run_used_software,
    "run_used_datasets": run_used_datasets,
    "run_generated": run_generated,
    "job_name": job_name,
    "job_description": job_description,
    "rule_ref": rule_ref,
    "dataset_refs": dataset_refs,
    "run_ref": run_ref,
    "param_strings": param_strings,
    "settings_author": settings_author,
    "settings_date": settings_date,
    "settings_keywords": settings_keywords,
    "date_or_published": date_or_published,
    "basename": basename,
    "workflow_description": workflow_description,
    "rule_description": rule_description,
    "rule_format": rule_format,
    "rule_content_url": rule_content_url,
    "workflow_ref": workflow_ref,
    "file_description": file_description,
    "encoding_format": encoding_format,
    "file_generated_by": file_generated_by,
    "file_is_part_of": file_is_part_of,
    "file_schema_ref": file_schema_ref,
    "file_content_url": file_content_url,
    "file_local_path": file_local_path,
    "size_string": size_string,
    "csv_constant": csv_constant,
}
