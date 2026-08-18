"""mlflow plugin parsers — the algorithm half of the mapping.

Every parser has the kernel signature ``fn(value, rule, ctx) -> value | None``
(``None`` = set nothing). The conversion state they read (``guid_map``,
``runs_by_id``, ``settings`` …) is computed once in the plugin's ``pre`` and
stashed in ``ctx.extras``.
"""

from __future__ import annotations

import mimetypes
import os

from ...core.parsers import scalar

REMOTE_SCHEMES = ("http://", "https://", "git://", "ssh://", "gs://", "s3://",
                  "wasbs://", "dbfs://", "ftp://")


# ---- plain helpers (shared with the plugin's pre/assemble) -----------------

def encoding_format_of(path):
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    ext = os.path.splitext(str(path))[1].lstrip(".")
    return ext or "unknown"


def ref(ark):
    return {"@id": ark}


def refs(arks):
    return [{"@id": a} for a in arks]


def file_display_name(path):
    return os.path.basename(str(path).rstrip("/")) or path


# ---- run --------------------------------------------------------------------

def run_name(value, rule, ctx):
    return f"MLflow run '{value}'"


def run_description(value, rule, ctx):
    run = ctx.node
    exp_name = ctx.extras["experiment"]["name"]
    description = (
        f"MLflow run '{value}' of experiment '{exp_name}', reconstructed "
        "post-hoc from the MLflow tracking store by mlflow-fairscape"
    )
    parent_id = run.get("parent_run_id")
    if parent_id:
        parent = ctx.extras["runs_by_id"].get(parent_id)
        if parent:
            description += f" (nested child of run '{parent['name']}')"
    status = run.get("status")
    if status and status != "FINISHED":
        description += f" (run status: {status})"
    return description


def run_user(value, rule, ctx):
    return value or ctx.extras["settings"]["author"]


def run_command(value, rule, ctx):
    """Best-effort invocation: MLflow records the source file, not argv."""
    source = ctx.extras["sources"].get(value) if value else None
    if not source:
        return None
    name = source["name"]
    if name.endswith(".py") and not name.startswith(REMOTE_SCHEMES):
        return f"python {name}"
    return name


def run_used_software(value, rule, ctx):
    g = ctx.extras["guid_map"]
    run = ctx.node
    arks = []
    if run.get("source_key"):
        arks.append(g[f"source:{run['source_key']}"])
    arks.append(g["engine"])
    return refs(arks)


def run_used_datasets(value, rule, ctx):
    g = ctx.extras["guid_map"]
    return refs([g[f"dataset:{d['key']}"] for d in (value or [])])


def run_generated(value, rule, ctx):
    g = ctx.extras["guid_map"]
    run = ctx.node
    arks = [g[f"file:{k}"] for k in run.get("artifacts", [])]
    arks += [g[f"model:{m}"] for m in run.get("models", [])]
    return refs(arks)


def run_parent_ref(value, rule, ctx):
    if not value:
        return None
    parent_ark = ctx.extras["guid_map"].get(f"run:{value}")
    return refs([parent_ark]) if parent_ark else None


def param_strings(value, rule, ctx):
    if not value:
        return None
    return [f"{k}={value[k]}" for k in sorted(value)]


def metric_property_values(value, rule, ctx):
    """Latest logged value per metric key, as schema.org PropertyValue."""
    if not value:
        return None
    return [{"@type": "PropertyValue", "name": k, "value": value[k]}
            for k in sorted(value)]


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
    return file_display_name(value)


def empty_list(value, rule, ctx):
    return []


def producer_run_ref(value, rule, ctx):
    producer = ctx.extras["guid_map"].get(f"run:{value}") if value else None
    return refs([producer]) if producer else []


def size_string(value, rule, ctx):
    return str(value) if value is not None else None


def csv_constant(value, rule, ctx):
    """Emit the rule's constant_value verbatim (the pattern the other plugins
    use for constants: a named parser reading rule.constant_value)."""
    return rule.constant_value


# ---- source / engine Software -----------------------------------------------

SOURCE_TYPE_LABEL = {
    "NOTEBOOK": "notebook",
    "JOB": "job",
    "PROJECT": "MLflow Project entry point",
    "LOCAL": "script",
    "RECIPE": "recipe",
}


def source_description(value, rule, ctx):
    src = ctx.node
    label = SOURCE_TYPE_LABEL.get(src.get("source_type"), "source")
    description = (f"The {label} '{file_display_name(value)}' logged by MLflow "
                   f"as the source of run(s) in experiment "
                   f"'{ctx.extras['experiment']['name']}'")
    if src.get("git_commit"):
        description += f" (git commit {src['git_commit']})"
    return description


def source_format(value, rule, ctx):
    name = str(value)
    if name.endswith(".py"):
        return "text/x-python"
    if name.endswith(".ipynb"):
        return "application/x-ipynb+json"
    return encoding_format_of(name)


def source_content_url(value, rule, ctx):
    if str(value).startswith(REMOTE_SCHEMES):
        return value
    return None


def source_local_path(value, rule, ctx):
    if str(value).startswith(REMOTE_SCHEMES):
        return None
    return value


# ---- dataset (logged mlflow dataset input) -----------------------------------

def dataset_description(value, rule, ctx):
    ds = ctx.node
    bits = []
    if ds.get("num_rows") is not None:
        bits.append(f"{ds['num_rows']} rows")
    if ds.get("digest"):
        bits.append(f"digest {ds['digest']}")
    detail = f" ({', '.join(bits)})" if bits else ""
    description = f"Dataset '{value}' logged as an MLflow run input{detail}"
    contexts = ds.get("contexts") or []
    if contexts:
        description += f", used as {'/'.join(contexts)} data"
    return description


def dataset_format(value, rule, ctx):
    return value or "unknown"


def dataset_schema_ref(value, rule, ctx):
    schema = ctx.extras["schemas"].get(f"dataset:{ctx.node['key']}")
    return ref(schema["@id"]) if schema else None


# ---- model (logged MLflow model) ---------------------------------------------

def model_description(value, rule, ctx):
    model = ctx.node
    run = ctx.extras["runs_by_id"].get(model.get("run_id"))
    description = f"MLflow model '{value}'"
    if model.get("flavor"):
        description += f" ({model['flavor']} flavor)"
    if run:
        description += f", logged by run '{run['name']}'"
    if model.get("mlflow_version"):
        description += f" with MLflow {model['mlflow_version']}"
    return description


def model_format(value, rule, ctx):
    return value or "mlflow-model"


# ---- file Datasets ------------------------------------------------------------

def file_description(value, rule, ctx):
    run = ctx.extras["runs_by_id"].get(ctx.node.get("run_id"))
    run_bit = f" run '{run['name']}'" if run else " a run"
    return (f"Artifact '{file_display_name(value)}' logged by MLflow{run_bit}")


def encoding_format(value, rule, ctx):
    return encoding_format_of(value)


def file_schema_ref(value, rule, ctx):
    schema = ctx.extras["schemas"].get(f"file:{ctx.node['key']}")
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


IMPORT_PARSERS = {
    "scalar": scalar,
    "run_name": run_name,
    "run_description": run_description,
    "run_user": run_user,
    "run_command": run_command,
    "run_used_software": run_used_software,
    "run_used_datasets": run_used_datasets,
    "run_generated": run_generated,
    "run_parent_ref": run_parent_ref,
    "param_strings": param_strings,
    "metric_property_values": metric_property_values,
    "settings_author": settings_author,
    "settings_date": settings_date,
    "settings_keywords": settings_keywords,
    "date_or_published": date_or_published,
    "basename": basename,
    "empty_list": empty_list,
    "producer_run_ref": producer_run_ref,
    "size_string": size_string,
    "csv_constant": csv_constant,
    "source_description": source_description,
    "source_format": source_format,
    "source_content_url": source_content_url,
    "source_local_path": source_local_path,
    "dataset_description": dataset_description,
    "dataset_format": dataset_format,
    "dataset_schema_ref": dataset_schema_ref,
    "model_description": model_description,
    "model_format": model_format,
    "file_description": file_description,
    "encoding_format": encoding_format,
    "file_schema_ref": file_schema_ref,
    "file_content_url": file_content_url,
    "file_local_path": file_local_path,
}
