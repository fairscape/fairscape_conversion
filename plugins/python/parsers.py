"""python plugin parsers — the algorithm half of the mapping.

Every parser has the kernel signature ``fn(value, rule, ctx) -> value | None``
(``None`` = set nothing). The conversion state they read (``guid_map``,
``settings`` …) is computed once in the plugin's ``pre`` and stashed in
``ctx.extras``.
"""

from __future__ import annotations

import os
import shlex

from ...core.parsers import encoding_format_of, scalar


def refs(arks):
    return [{"@id": a} for a in arks]


def _files(ctx, role):
    g = ctx.extras["guid_map"]
    files = ctx.extras["files"]
    return refs([g[f"file:{p}"] for p in sorted(files) if files[p]["role"] == role])


# ---- run --------------------------------------------------------------------

def run_name(value, rule, ctx):
    return f"Python run of '{value}'"


def run_description(value, rule, ctx):
    return f"Execution of the Python code '{value}', recorded by fairscape_conversion track"


def run_command(value, rule, ctx):
    return shlex.join(["python", *value]) if value else None


def software_refs(value, rule, ctx):
    return refs([ctx.extras["guid_map"]["software"]])


def input_refs(value, rule, ctx):
    return _files(ctx, "input")


def output_refs(value, rule, ctx):
    return _files(ctx, "output")


def exit_code(value, rule, ctx):
    return str(value) if value else None


# ---- software -----------------------------------------------------------------

def software_name(value, rule, ctx):
    script = ctx.node["script"]
    return script.get("name") or os.path.basename(script["locator_value"])


def software_description(value, rule, ctx):
    return f"Python code '{value}' executed by the tracked run"


# ---- file Datasets ----------------------------------------------------------

def file_description(value, rule, ctx):
    run = ctx.extras["run"]["name"]
    if ctx.node["role"] == "output":
        return f"File '{os.path.basename(value)}' written by the Python run '{run}'"
    return f"Input file '{os.path.basename(value)}' read by the Python run '{run}'"


def file_generated_by(value, rule, ctx):
    return refs([ctx.extras["guid_map"]["run"]]) if value == "output" else []


# ---- shared field sources ---------------------------------------------------

def settings_author(value, rule, ctx):
    return ctx.extras["settings"]["author"]


def settings_date(value, rule, ctx):
    return ctx.extras["settings"]["date_published"]


def settings_keywords(value, rule, ctx):
    return ctx.extras["settings"]["keywords"]


def basename(value, rule, ctx):
    return os.path.basename(value)


def encoding_format(value, rule, ctx):
    return encoding_format_of(value)


def locator_content_url(value, rule, ctx):
    loc = ctx.node.get("script", ctx.node)
    return loc["locator_value"] if loc["locator"] == "contentUrl" else None


def locator_local_path(value, rule, ctx):
    loc = ctx.node.get("script", ctx.node)
    return loc["locator_value"] if loc["locator"] == "localPath" else None


def size_string(value, rule, ctx):
    return str(value) if value is not None else None


def csv_constant(value, rule, ctx):
    return rule.constant_value


IMPORT_PARSERS = {
    "scalar": scalar,
    "run_name": run_name,
    "run_description": run_description,
    "run_command": run_command,
    "software_refs": software_refs,
    "input_refs": input_refs,
    "output_refs": output_refs,
    "exit_code": exit_code,
    "software_name": software_name,
    "software_description": software_description,
    "file_description": file_description,
    "file_generated_by": file_generated_by,
    "settings_author": settings_author,
    "settings_date": settings_date,
    "settings_keywords": settings_keywords,
    "basename": basename,
    "encoding_format": encoding_format,
    "locator_content_url": locator_content_url,
    "locator_local_path": locator_local_path,
    "size_string": size_string,
    "csv_constant": csv_constant,
}
