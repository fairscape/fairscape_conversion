"""cromwell plugin parsers — the algorithm half of the mapping.

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
    qualifiers = []
    if job["shard"] >= 0:
        qualifiers.append(f"shard={job['shard']}")
    if job["attempt"] > 1:
        qualifiers.append(f"attempt={job['attempt']}")
    if qualifiers:
        return f"{job['task']} ({', '.join(qualifiers)})"
    return job["task"]


def file_display_name(path):
    return os.path.basename(path.rstrip("/")) or path


# ---- run --------------------------------------------------------------------

def run_name(value, rule, ctx):
    return f"Cromwell workflow run of '{value}'"


def run_description(value, rule, ctx):
    description = (
        f"Execution of the WDL workflow '{value}' by Cromwell, "
        "reconstructed post-hoc from Cromwell's run metadata by "
        "cromwell-fairscape"
    )
    status = ctx.node.get("status")
    if status and status != "Succeeded":
        description += f" (workflow status: {status})"
    return description


def run_used_software(value, rule, ctx):
    g = ctx.extras["guid_map"]
    return refs([g["workflow"], g["engine"]])


def run_used_datasets(value, rule, ctx):
    g = ctx.extras["guid_map"]
    return refs([g[f"file:{p}"] for p in ctx.extras["root_inputs"]])


def run_generated(value, rule, ctx):
    g = ctx.extras["guid_map"]
    return refs([g[f"file:{p}"] for p in ctx.extras["run_outputs"]])


# ---- job (one Cromwell call) ------------------------------------------------

def job_name(value, rule, ctx):
    return job_display_name(ctx.node)


def job_description(value, rule, ctx):
    job = ctx.node
    description = f"Cromwell call of WDL task '{job['task']}'"
    if job["shard"] >= 0:
        description += f", scatter shard {job['shard']}"
    if job.get("status") and job["status"] != "Done":
        description += f" (execution status: {job['status']})"
    return description


def task_ref(value, rule, ctx):
    return refs([ctx.extras["guid_map"][f"task:{value}"]])


def dataset_refs(value, rule, ctx):
    g = ctx.extras["guid_map"]
    return refs([g[f"file:{p}"] for p in (value or [])])


def run_ref(value, rule, ctx):
    return refs([ctx.extras["guid_map"]["run"]])


def param_strings(value, rule, ctx):
    return value or None


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


# ---- workflow / engine / task Software --------------------------------------

def workflow_description(value, rule, ctx):
    language = ctx.extras["run"]["language"]
    return (f"{language} workflow definition "
            f"'{os.path.basename(value)}' for this run")


def task_description(value, rule, ctx):
    return ensure_description(
        value,
        f"WDL task '{ctx.node['name']}' from '{ctx.extras['run']['wdl_ref']}'")


def wdl_ref_url(value, rule, ctx):
    return ctx.extras["run"]["wdl_ref"]


def workflow_ref(value, rule, ctx):
    return refs([ctx.extras["guid_map"]["workflow"]])


# ---- file Datasets ----------------------------------------------------------

def file_name(value, rule, ctx):
    return file_display_name(value)


def file_description(value, rule, ctx):
    info = ctx.node
    name = file_display_name(value)
    if info["is_config"]:
        return f"File '{name}' submitted to Cromwell for this run"
    if ctx.extras["produced_by"].get(value):
        return f"File '{name}' produced by the Cromwell workflow run"
    return f"Input file '{name}' used by the Cromwell workflow run"


def encoding_format(value, rule, ctx):
    return encoding_format_of(value)


def file_generated_by(value, rule, ctx):
    producer = ctx.extras["produced_by"].get(value)
    return refs([producer]) if producer else []


def file_is_part_of(value, rule, ctx):
    if ctx.node["is_config"]:
        return refs([ctx.extras["guid_map"]["workflow"]])
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
    "task_ref": task_ref,
    "dataset_refs": dataset_refs,
    "run_ref": run_ref,
    "param_strings": param_strings,
    "settings_author": settings_author,
    "settings_date": settings_date,
    "settings_keywords": settings_keywords,
    "date_or_published": date_or_published,
    "basename": basename,
    "workflow_description": workflow_description,
    "task_description": task_description,
    "wdl_ref_url": wdl_ref_url,
    "workflow_ref": workflow_ref,
    "file_name": file_name,
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
