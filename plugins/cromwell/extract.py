"""cromwell plugin extraction — Cromwell run metadata JSON -> plain records.

This is the I/O half of the conversion: everything that touches the
filesystem or depends on where the crate will be written happens here, so the
mapping itself (``convert("import", records)``) stays a pure function and the
golden-file test stays hermetic. Ported from the standalone
``nf/cromwell-fairscape`` converter, which remains the parity reference.

Facts about the metadata format this relies on (verified against Cromwell 92):
- call-level ``inputs`` hold the *pre-localization* source paths, so a
  consumer's input path string equals the producer's output path and the
  provenance graph falls out of exact path matching;
- ``dockerImageUsed`` is the digest-pinned image the call actually ran in
  (``runtimeAttributes.docker`` is the declared one, kept as fallback);
- ``workflowProcessingEvents[].cromwellVersion`` names the engine version;
- ``submittedFiles.workflow``/``.inputs`` hold the exact submitted WDL source
  and inputs JSON, which are written into the crate when not already present.

File-vs-parameter is a heuristic (metadata JSON is untyped): a string value is
a file if it is a remote URI (gs/s3/drs/http...), lives under the run's
workflowRoot/callRoots, or exists on disk relative to the metadata file.
"""

from __future__ import annotations

import getpass
import json
import os
import re
from datetime import datetime, timezone

REMOTE_SCHEMES = ("gs://", "s3://", "drs://", "http://", "https://", "ftp://")
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def leaf_strings(value):
    """Yield every string leaf of a nested metadata value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from leaf_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from leaf_strings(v)


def iter_calls(calls, workflow_name):
    """Yield (task_name, attempt_dict) for the last attempt of each executed
    call shard, recursing into inlined subworkflow metadata."""
    for call_name, attempts in (calls or {}).items():
        task = call_name[len(workflow_name) + 1:] \
            if call_name.startswith(workflow_name + ".") else call_name
        by_shard = {}
        for a in attempts:
            shard = a.get("shardIndex", -1)
            if shard not in by_shard or a.get("attempt", 1) >= by_shard[shard].get("attempt", 1):
                by_shard[shard] = a
        for shard in sorted(by_shard):
            a = by_shard[shard]
            sub = a.get("subWorkflowMetadata")
            if sub:
                yield from iter_calls(sub.get("calls"),
                                      sub.get("workflowName", task))
            elif a.get("start"):
                yield task, a


def task_source(wdl_source, task_name):
    """Extract the ``task <name> { ... }`` block from WDL source by brace
    matching; None when not found (e.g. imported tasks or odd quoting)."""
    match = re.search(r"^[ \t]*task\s+%s\s*\{" % re.escape(task_name),
                      wdl_source or "", re.MULTILINE)
    if not match:
        return None
    depth, start = 0, match.start()
    for i in range(match.end() - 1, len(wdl_source)):
        if wdl_source[i] == "{":
            depth += 1
        elif wdl_source[i] == "}":
            depth -= 1
            if depth == 0:
                return wdl_source[start:i + 1]
    return None


def materialize(text, candidates, fallback_name, crate_dir):
    """Ensure a submitted file (WDL source, inputs JSON) exists in the crate.

    Reference an existing file whose content already matches; otherwise write
    the text to fallback_name (suffixed .submitted.* when the plain name is
    taken by different content). Returns the crate-relative reference.
    """
    for cand in candidates + [fallback_name]:
        if not cand or os.path.isabs(cand) or cand.startswith(REMOTE_SCHEMES):
            continue
        path = os.path.join(crate_dir, cand)
        try:
            if open(path).read() == text:
                return cand
        except OSError:
            continue
    target = fallback_name
    if os.path.exists(os.path.join(crate_dir, target)):
        stem, ext = os.path.splitext(fallback_name)
        target = f"{stem}.submitted{ext}"
    with open(os.path.join(crate_dir, target), "w") as f:
        f.write(text)
    return target


def infer_schemas(files, naan, base_dir):
    """Infer an EVI Schema node per described data file with a supported
    extension.

    Delegates to fairscape_cli.models.schema.infer_schema (which dispatches on
    extension: csv/tsv/parquet/h5/hdf5/hea/dcm), overriding the CLI's
    random-uuid guid with a deterministic ARK hashed from the Dataset's ARK so
    crates stay reproducible across conversion re-runs — the same delegation
    snakemake-report-plugin-fairscape performs.
    """
    try:
        from fairscape_cli.models.schema import infer_schema
        from fairscape_models.schema.registry import EXTENSION_MAP
    except ImportError:
        print("NOTE: fairscape-cli not importable; skipping schema inference")
        return {}

    from ...core.arks import mint_ark

    schemas = {}
    for path in sorted(files):
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if ext not in EXTENSION_MAP or path.startswith(REMOTE_SCHEMES):
            continue
        abs_p = os.path.normpath(path if os.path.isabs(path)
                                 else os.path.join(base_dir, path))
        if not os.path.isfile(abs_p):
            continue
        basename = os.path.basename(path.rstrip("/")) or path
        dataset_ark = mint_ark(naan, "dataset", basename,
                               files[path]["ark_source"])
        schema_ark = mint_ark(naan, "schema", basename, dataset_ark)
        try:
            model = infer_schema(
                abs_p,
                name=f"Schema for {basename}",
                description=f"Schema inferred from the {ext} file '{path}' "
                "by cromwell-fairscape",
                guid=schema_ark)
            schemas[path] = model.model_dump(by_alias=True, exclude_none=True)
        except Exception as e:
            print(f"WARNING: schema inference failed for '{path}': {e}")
    return schemas


def extract(metadata_path, crate_dir=None, naan="59853", name=None,
            description=None, author=None, keywords=None,
            license="https://spdx.org/licenses/CC-BY-4.0",
            crate_version="1.0", date_published=None, schemas=False):
    """Cromwell metadata JSON file -> the plain records dict the plugin maps.

    ``crate_dir`` is where the crate will be written (default: next to the
    metadata file); it anchors contentUrl/localPath decisions and is where the
    submitted WDL/inputs files are materialized. ``date_published`` pins the
    crate timestamp (default: now) — pass it for reproducible output.
    ``schemas=True`` additionally infers an EVI Schema per supported data file
    (reads the data files; needs fairscape-cli importable).
    """
    with open(metadata_path) as f:
        meta = json.load(f)

    base_dir = os.path.dirname(os.path.abspath(metadata_path))
    crate_dir = os.path.abspath(crate_dir or base_dir)
    os.makedirs(crate_dir, exist_ok=True)

    workflow_name = meta.get("workflowName", "workflow")
    workflow_url = (meta.get("submittedFiles") or {}).get("workflowUrl") or None
    if workflow_url and not workflow_url.startswith(REMOTE_SCHEMES):
        # cromwell records the URL exactly as submitted; normalize so
        # './letters.wdl' and 'letters.wdl' runs mint the same ARKs
        workflow_url = os.path.normpath(workflow_url)
    wdl_source = (meta.get("submittedFiles") or {}).get("workflow") or ""
    inputs_json = (meta.get("submittedFiles") or {}).get("inputs") or ""
    version = next((e["cromwellVersion"]
                    for e in meta.get("workflowProcessingEvents", [])
                    if e.get("cromwellVersion")), "unknown")
    workflow_root = meta.get("workflowRoot") or ""

    # sort for a deterministic graph order regardless of the JSON's dict order
    jobs_raw = sorted(iter_calls(meta.get("calls"), workflow_name),
                      key=lambda ta: (ta[0], ta[1].get("shardIndex", -1)))
    roots = [workflow_root] + [a["callRoot"] for _, a in jobs_raw if a.get("callRoot")]
    roots = [os.path.normpath(r) for r in roots if r]

    def resolve(path, rel_to=None):
        """Absolute path for a metadata path string.

        Cromwell records workflow and call inputs exactly as they were
        submitted, so a relative path is relative to the directory Cromwell
        ran in — which is the crate directory in the usual layout, and not
        necessarily where the metadata file was written (``cromwell run -m
        run/metadata.json`` puts it a level down). Resolve against the
        metadata file's directory first, then the crate directory; a path
        that exists under either is the same file.
        """
        if os.path.isabs(path):
            return os.path.normpath(path)
        for base in (rel_to or base_dir, crate_dir):
            candidate = os.path.normpath(os.path.join(base, path))
            if os.path.exists(candidate):
                return candidate
        return os.path.normpath(os.path.join(rel_to or base_dir, path))

    def is_file(s):
        if s.startswith(REMOTE_SCHEMES):
            return True
        norm = resolve(s)
        if any(norm == r or norm.startswith(r + os.sep) for r in roots):
            return True
        return os.path.exists(norm)

    # wdl_key is the run-independent identity all ARKs hash: the submitted
    # workflow reference when there is one, else the workflow name — stable
    # across re-runs and across edits of the WDL
    wdl_key = f"{workflow_name}:{workflow_url or 'inline'}"

    def ark_source(path):
        if path.startswith(REMOTE_SCHEMES):
            return path
        norm = resolve(path)
        if workflow_root and (norm.startswith(os.path.normpath(workflow_root) + os.sep)):
            rel = os.path.relpath(norm, workflow_root)
            # subworkflow call dirs embed their own run UUID; blank any so
            # re-runs mint the same dataset ARKs
            return wdl_key + "#run/" + UUID_RE.sub("-", rel)
        return norm

    files = {}

    def register(path, is_config=False, ark_key=None, rel_to=None):
        if path in files:
            return
        info = {"size": None, "is_config": is_config,
                "ark_source": ark_key or ark_source(path)}
        if path.startswith(REMOTE_SCHEMES):
            info["locator"], info["locator_value"] = "contentUrl", path
        else:
            abs_p = resolve(path, rel_to)
            if os.path.isfile(abs_p):
                info["size"] = os.path.getsize(abs_p)
            try:
                inside = os.path.commonpath([abs_p, crate_dir]) == crate_dir
            except ValueError:
                inside = False
            if inside and os.path.exists(abs_p):
                info["locator"] = "contentUrl"
                info["locator_value"] = os.path.relpath(abs_p, crate_dir)
            else:
                info["locator"] = "localPath"
                info["locator_value"] = path
        files[path] = info

    jobs = []
    tasks = {}
    for task, a in jobs_raw:
        inputs, parameters = [], []
        for key, value in (a.get("inputs") or {}).items():
            paths = [s for s in leaf_strings(value) if is_file(s)]
            if paths:
                inputs.extend(paths)
            elif value is not None:
                parameters.append(
                    f"{key}={value if isinstance(value, str) else json.dumps(value)}")
        outputs = [s for s in leaf_strings(a.get("outputs")) if is_file(s)]
        for p in outputs + inputs:
            register(p)
        container = a.get("dockerImageUsed") \
            or (a.get("runtimeAttributes") or {}).get("docker")
        jobs.append({
            "task": task,
            "shard": a.get("shardIndex", -1),
            "attempt": a.get("attempt", 1),
            "shellcmd": a.get("commandLine"),
            "parameters": parameters,
            "inputs": inputs,
            "outputs": outputs,
            "starttime": a.get("start"),
            "endtime": a.get("end"),
            "container": container,
            "status": a.get("executionStatus"),
        })
        if task not in tasks:
            tasks[task] = {
                "source": task_source(wdl_source, task),
                "container": (a.get("runtimeAttributes") or {}).get("docker"),
            }

    # workflow-level inputs may name files no call consumed
    for s in leaf_strings(meta.get("inputs")):
        if is_file(s):
            register(s)
    run_outputs = []
    for s in leaf_strings(meta.get("outputs")):
        if is_file(s):
            register(s)
            run_outputs.append(s)

    # the submitted WDL and inputs JSON become part of the crate
    wdl_ref = materialize(wdl_source, [workflow_url], f"{workflow_name}.wdl",
                          crate_dir)
    register(wdl_ref, is_config=True, ark_key=wdl_key + "#workflow",
             rel_to=crate_dir)
    if inputs_json.strip() not in ("", "{}"):
        inputs_ref = materialize(inputs_json, [], "inputs.json", crate_dir)
        register(inputs_ref, is_config=True, ark_key=wdl_key + "#inputs",
                 rel_to=crate_dir)

    author = author or getpass.getuser()
    # keywords come either as a comma-separated string (CLI, GUI form) or as a
    # list (Python callers) — accept both
    if isinstance(keywords, str):
        keywords = keywords.split(",")
    keyword_list = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    settings = {
        "naan": naan,
        "name": name or f"Cromwell run of WDL workflow '{workflow_name}'",
        "description": description
        or f"FAIRSCAPE EVI RO-Crate describing a Cromwell run of the WDL "
        f"workflow '{workflow_name}'",
        "author": author,
        "keywords": keyword_list or ["cromwell", "wdl", "workflow"],
        "license": license,
        "version": crate_version,
        "date_published": date_published
        or datetime.now(timezone.utc).astimezone().isoformat(),
    }
    run_info = {
        "name": settings["name"],
        "workflow_name": workflow_name,
        "wdl_ref": wdl_ref,
        "wdl_key": wdl_key,
        "language": " ".join(filter(None, [meta.get("actualWorkflowLanguage"),
                                           meta.get("actualWorkflowLanguageVersion")]))
        or "WDL",
        "engine_version": version,
        "workflow_id": meta.get("id"),
        "command": f"cromwell run {workflow_url or wdl_ref}",
        "status": meta.get("status"),
        "starttime": meta.get("start"),
        "endtime": meta.get("end"),
    }

    records = {
        "settings": settings,
        "run": run_info,
        "jobs": jobs,
        "tasks": tasks,
        "files": files,
        "run_outputs": run_outputs,
    }
    if schemas:
        records["schemas"] = infer_schemas(files, naan, base_dir)
    return records
