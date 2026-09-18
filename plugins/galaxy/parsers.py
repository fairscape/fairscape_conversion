"""galaxy plugin parsers — the algorithm half of the mapping.

Kernel signature throughout: ``fn(value, rule, ctx) -> value | None``. The
conversion state they read (``guid_map``, ``by_dataset``, ``by_collection``,
``produced_by`` …) is computed once in the plugin's ``pre``.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from ...core.parsers import encoding_format_of, scalar

HERE = Path(__file__).resolve().parent
TOOLSHED = re.compile(r"^(?P<host>[^/]+)/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<tool>[^/]+)/(?P<version>[^/]+)$")


def load_datatypes() -> dict[str, str]:
    with open(HERE / "field_types.csv", newline="") as f:
        return {r["extension"]: r["mime_type"] for r in csv.DictReader(f) if r.get("extension")}


DATATYPES = load_datatypes()


# ---- helpers ----------------------------------------------------------------------

def ref(ark):
    return {"@id": ark}


def refs(arks):
    return [{"@id": a} for a in arks]


def _settings(ctx):
    return ctx.source["settings"]


def _guid(ctx, key):
    return ctx.extras["guid_map"].get(key)


def dataset_ark(ctx, encoded_id):
    return _guid(ctx, "dataset:" + encoded_id)


def collection_ark(ctx, encoded_id):
    return _guid(ctx, "collection:" + encoded_id)


def _dedupe(arks):
    out = []
    for a in arks:
        if a and a not in out:
            out.append(a)
    return out


def tool_short_name(tool_id: str) -> str:
    match = TOOLSHED.match(tool_id or "")
    return match.group("tool") if match else (tool_id or "tool")


def iso_datetime(value, rule, ctx):
    """Galaxy writes ``2023-03-28 13:52:42.214286`` or with a ``T``; emit
    ISO 8601 with a ``T`` and no fractional seconds."""
    if not value:
        return None
    text = str(value).replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return text


def identity(value, rule, ctx):
    return value if value not in (None, "", [], {}) else None


def crate_author(value, rule, ctx):
    return _settings(ctx).get("author") or None


def crate_date(value, rule, ctx):
    return _settings(ctx)["date_published"]


def crate_keywords(value, rule, ctx):
    return list(_settings(ctx).get("keywords") or []) or None


def flatten_params(params, prefix="") -> list[str]:
    out = []
    for key, value in (params or {}).items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.extend(flatten_params(value, name + "|"))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    out.extend(flatten_params(item, f"{name}_{i}|"))
                else:
                    out.append(f"{name}_{i}={item}")
        else:
            out.append(f"{name}={value}")
    return out


# ---- run (the invocation) ---------------------------------------------------------

def run_name(value, rule, ctx):
    return f"Galaxy invocation of '{_settings(ctx)['name']}'"


def run_description(value, rule, ctx):
    inv = ctx.node
    jobs_in = [j for j in ctx.source["jobs"] if j.get("step_index") is not None]
    text = (f"Invocation of the Galaxy workflow '{_settings(ctx)['name']}' "
            f"({len(inv['steps'])} steps, {len(jobs_in)} tool jobs), state '{inv.get('state')}'"
            + (f", on Galaxy {inv['galaxy_version']}" if inv.get("galaxy_version") else "")
            + ". Reconstructed from Galaxy's invocation export (model store) by fairscape_conversion.")
    return text


def run_used_software(value, rule, ctx):
    return refs(_dedupe([_guid(ctx, "workflow"), _guid(ctx, "engine")]))


def run_used_datasets(value, rule, ctx):
    inv = ctx.node
    arks = [dataset_ark(ctx, d) for d in inv["input_datasets"]]
    arks += [collection_ark(ctx, c) for c in inv["input_collections"]]
    return refs(_dedupe(arks)) or None


def run_generated(value, rule, ctx):
    inv = ctx.node
    arks = [dataset_ark(ctx, d["id"]) for d in inv["output_datasets"]]
    arks += [collection_ark(ctx, c["id"]) for c in inv["output_collections"]]
    return refs(_dedupe(arks)) or None


def run_parameters(value, rule, ctx):
    return [f"{p['label']}={p['value']}" for p in ctx.node.get("input_parameters") or []] or None


# ---- job --------------------------------------------------------------------------

def _step(ctx, job):
    index = job.get("step_index")
    if index is None:
        return None
    return next((s for s in ctx.source["invocation"]["steps"] if s["index"] == index), None)


def job_name(value, rule, ctx):
    job = ctx.node
    step = _step(ctx, job)
    tool = tool_short_name(job.get("tool_id"))
    if step:
        label = step.get("label")
        return f"{tool} (step {step['index']}" + (f": {label}" if label and label != tool else "") + ")"
    if job.get("tool_id") in ("__DATA_FETCH__", "upload1"):
        return f"upload ({tool})"
    return f"{tool} (outside the invocation)"


def job_description(value, rule, ctx):
    job = ctx.node
    step = _step(ctx, job)
    text = (f"Galaxy job running tool '{job.get('tool_id')}'"
            + (f" version {job['tool_version']}" if job.get("tool_version") else "")
            + f", state '{job.get('state')}'"
            + (f", exit code {job['exit_code']}" if job.get("exit_code") is not None else ""))
    if step:
        text += f"; step {step['index']} of the invocation"
        wf_step = next((s for s in (ctx.source.get("workflow") or {}).get("steps", [])
                        if s["index"] == step["index"]), None)
        if wf_step and wf_step.get("annotation"):
            text += f" ({wf_step['annotation']})"
    elif job.get("tool_id") in ("__DATA_FETCH__", "upload1"):
        text += "; an upload that produced an input of the invocation"
    return text + "."


def job_used_software(value, rule, ctx):
    job = ctx.node
    return refs(_dedupe([_guid(ctx, f"tool:{job.get('tool_id')}@{job.get('tool_version') or ''}")]))


def job_used_datasets(value, rule, ctx):
    job = ctx.node
    arks = [dataset_ark(ctx, d) for d in job["inputs"]]
    arks += [collection_ark(ctx, c) for c in job["input_collections"]]
    return refs(_dedupe(arks)) or None


def job_generated(value, rule, ctx):
    job = ctx.node
    arks = [dataset_ark(ctx, d) for d in job["outputs"]]
    arks += [collection_ark(ctx, c) for c in job["output_collections"]]
    # a collection-producing job also made the elements it lists
    for c in job["output_collections"]:
        for element in ctx.extras["by_collection"].get(c, {}).get("elements", []):
            if element.get("dataset"):
                arks.append(dataset_ark(ctx, element["dataset"]))
    return refs(_dedupe(arks)) or None


def job_part_of(value, rule, ctx):
    if ctx.node.get("step_index") is None:
        return None
    return [ref(_guid(ctx, "run"))]


def job_parameters(value, rule, ctx):
    return flatten_params(value) or None


# ---- software ---------------------------------------------------------------------

def workflow_description(value, rule, ctx):
    wf = ctx.node
    tools = [s for s in wf["steps"] if s["type"] == "tool"]
    inputs = [s for s in wf["steps"] if s["type"] != "tool"]
    text = (f"Galaxy workflow '{wf['name']}'"
            + (f": {wf['annotation']}" if wf.get("annotation") else "")
            + f". {len(wf['steps'])} steps: {len(inputs)} input(s) and {len(tools)} tool step(s)"
            + (" (" + ", ".join(tool_short_name(s["tool_id"]) for s in tools) + ")" if tools else "")
            + ".")
    return text


def workflow_author(value, rule, ctx):
    return ", ".join(ctx.node.get("creators") or []) or _settings(ctx).get("author") or None


def workflow_tags(value, rule, ctx):
    return list(ctx.node.get("tags") or []) or None


def constant_ga_format(value, rule, ctx):
    return "application/json"


def constant_galaxy(value, rule, ctx):
    return "Galaxy"


def engine_description(value, rule, ctx):
    return ("The Galaxy platform (galaxyproject.org), which scheduled the workflow "
            "invocation and ran each tool job")


def constant_galaxy_url(value, rule, ctx):
    return "https://galaxyproject.org"


def constant_galaxy_author(value, rule, ctx):
    return "The Galaxy Community"


def constant_web_app(value, rule, ctx):
    return "application/x-web-application"


def tool_name(value, rule, ctx):
    return tool_short_name(value)


def tool_description(value, rule, ctx):
    tool_id = ctx.node.get("tool_id") or ""
    match = TOOLSHED.match(tool_id)
    if match:
        return (f"Galaxy tool '{match.group('tool')}' from the ToolShed repository "
                f"{match.group('owner')}/{match.group('repo')} on {match.group('host')}")
    if tool_id.startswith("__") and tool_id.endswith("__"):
        return f"Galaxy built-in model operation '{tool_id}'"
    return f"Galaxy tool '{tool_id}' (built into the Galaxy server)"


def tool_url(value, rule, ctx):
    match = TOOLSHED.match(value or "")
    if not match:
        return None
    return f"https://{match.group('host')}/view/{match.group('owner')}/{match.group('repo')}/{match.group('version')}"


def constant_tool_format(value, rule, ctx):
    return "application/x-galaxy-tool"


# ---- datasets -----------------------------------------------------------------------

def dataset_description(value, rule, ctx):
    d = ctx.node
    copies = ctx.extras["copies"].get(d["key"], [d])
    hids = sorted(c["hid"] for c in copies if c.get("hid") is not None)
    text = f"Galaxy dataset of type '{d['extension']}'"
    if d.get("blurb"):
        text += f", {d['blurb']}"
    if d.get("info"):
        text += f"; {d['info']}"
    if hids:
        text += f". History item{'s' if len(hids) > 1 else ''} #{', #'.join(str(h) for h in hids)}"
        if len(copies) > 1:
            text += f" ({len(copies)} history copies of one file)"
    return text + "."


def dataset_format(value, rule, ctx):
    ext = (value or "data").lower()
    return DATATYPES.get(ext) or encoding_format_of("x." + ext)


def galaxy_datatype(value, rule, ctx):
    return value or None


def dataset_hash_md5(value, rule, ctx):
    return (ctx.node.get("hashes") or {}).get("md5")


def dataset_hash_sha256(value, rule, ctx):
    return (ctx.node.get("hashes") or {}).get("sha-256") or (ctx.node.get("hashes") or {}).get("sha256")


def dataset_generated_by(value, rule, ctx):
    job = ctx.extras["produced_by"].get(dataset_ark(ctx, ctx.node["encoded_id"]))
    return ref(job) if job else None


def collection_description(value, rule, ctx):
    c = ctx.node
    names = [e.get("identifier") for e in c["elements"] if e.get("identifier")]
    return (f"Galaxy dataset collection of type '{c.get('type')}' with {len(c['elements'])} element(s)"
            + (": " + ", ".join(names) if names else "") + ".")


def constant_collection_format(value, rule, ctx):
    return "application/vnd.galaxy.collection"


def collection_parts(value, rule, ctx):
    arks = []
    for e in ctx.node["elements"]:
        if e.get("dataset"):
            arks.append(dataset_ark(ctx, e["dataset"]))
        elif e.get("collection"):
            arks.append(collection_ark(ctx, e["collection"]))
    return refs(_dedupe(arks)) or None


def collection_generated_by(value, rule, ctx):
    job = ctx.extras["produced_by"].get(collection_ark(ctx, ctx.node["encoded_id"]))
    return ref(job) if job else None


def collection_type(value, rule, ctx):
    return f"galaxy:{value}" if value else None


IMPORT_PARSERS = {
    "scalar": scalar,
    "identity": identity,
    "iso_datetime": iso_datetime,
    "crate_author": crate_author,
    "crate_date": crate_date,
    "crate_keywords": crate_keywords,
    "run_name": run_name,
    "run_description": run_description,
    "run_used_software": run_used_software,
    "run_used_datasets": run_used_datasets,
    "run_generated": run_generated,
    "run_parameters": run_parameters,
    "job_name": job_name,
    "job_description": job_description,
    "job_used_software": job_used_software,
    "job_used_datasets": job_used_datasets,
    "job_generated": job_generated,
    "job_part_of": job_part_of,
    "job_parameters": job_parameters,
    "workflow_description": workflow_description,
    "workflow_author": workflow_author,
    "workflow_tags": workflow_tags,
    "constant_ga_format": constant_ga_format,
    "constant_galaxy": constant_galaxy,
    "engine_description": engine_description,
    "constant_galaxy_url": constant_galaxy_url,
    "constant_galaxy_author": constant_galaxy_author,
    "constant_web_app": constant_web_app,
    "tool_name": tool_name,
    "tool_description": tool_description,
    "tool_url": tool_url,
    "constant_tool_format": constant_tool_format,
    "dataset_description": dataset_description,
    "dataset_format": dataset_format,
    "galaxy_datatype": galaxy_datatype,
    "dataset_hash_md5": dataset_hash_md5,
    "dataset_hash_sha256": dataset_hash_sha256,
    "dataset_generated_by": dataset_generated_by,
    "collection_description": collection_description,
    "constant_collection_format": constant_collection_format,
    "collection_parts": collection_parts,
    "collection_generated_by": collection_generated_by,
    "collection_type": collection_type,
}
