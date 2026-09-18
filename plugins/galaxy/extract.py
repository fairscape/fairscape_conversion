"""galaxy plugin extraction — Galaxy's own exports -> plain records.

The I/O half (the ``plugins/cromwell/extract.py`` mould). Three things Galaxy
hands you, all read here into one record shape so the mapping never knows
which it got:

* **an invocation export** — *User → Workflow Invocations → Export*, or
  ``POST /api/invocations/{id}/prepare_store_download``. Whatever container
  you pick (``.tar.gz``, ``.zip``, ``.rocrate.zip``, or an unpacked folder)
  the payload is Galaxy's *model store*: ``invocation_attrs.txt``,
  ``jobs_attrs.txt``, ``datasets_attrs.txt``, ``collections_attrs.txt`` (JSON
  despite the name) and ``workflows/<id>.ga``. This is the primary path: it
  carries what the Workflow Run RO-Crate flavour of the same export leaves
  out — every job's parameters, command line, state and exit code, tool
  versions, dataset hashes, and the upload jobs that made the inputs.
* **a bare ``.ga`` file** — the workflow definition alone. No run, so no
  Computations: the workflow and its tools become Software nodes.
* **a Galaxy server** — ``extract("https://usegalaxy.example", api_key=...,
  invocation_id=...)`` asks the server for the invocation export, downloads
  it, and reads it as above. (Model store download API, Galaxy >= 22.05.)

Records shape (``input.json`` is one): ``settings``; ``invocation`` (or
None for a bare .ga); ``workflow``; ``jobs``; ``datasets`` (one per HDA,
each with a ``key`` that collapses history copies of the same file);
``collections``; ``tools`` (distinct tool_id + tool_version).
"""

from __future__ import annotations

import io
import json
import os
import re
import tarfile
import tempfile
import time
import zipfile
from datetime import date

from ...core.arks import DEFAULT_NAAN

STORE_FILES = ("invocation_attrs.txt", "jobs_attrs.txt", "datasets_attrs.txt",
               "collections_attrs.txt")
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar", ".zip", ".rocrate.zip", ".bag.zip")


# ---- locating the store ---------------------------------------------------------

def _read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    return json.loads(text) if text else default


def unpack(archive: str) -> str:
    """Unpack an export archive to a temp dir and return the store root."""
    out = tempfile.mkdtemp(prefix="galaxy-export-")
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(out)
    else:
        with tarfile.open(archive) as t:
            t.extractall(out)
    return find_store(out)


def find_store(path: str) -> str:
    """The directory holding invocation_attrs.txt, searching one level down
    (archives often wrap the store in a folder)."""
    if os.path.isfile(os.path.join(path, "invocation_attrs.txt")):
        return path
    for name in sorted(os.listdir(path)):
        sub = os.path.join(path, name)
        if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "invocation_attrs.txt")):
            return sub
    raise FileNotFoundError(f"no invocation_attrs.txt under {path}: not a Galaxy invocation export")


# ---- the .ga workflow definition -----------------------------------------------------

def read_ga(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        ga = json.load(f)
    if str(ga.get("a_galaxy_workflow", "")).lower() != "true" or "steps" not in ga:
        raise ValueError(f"{path}: not a Galaxy workflow (.ga) file")
    return ga


def _step_inputs(step: dict) -> list[str]:
    return sorted((step.get("input_connections") or {}).keys())


def workflow_record(ga: dict, file_path: str | None, crate_dir) -> dict:
    steps = []
    for index, step in sorted(((int(k), v) for k, v in ga["steps"].items())):
        steps.append({
            "index": index,
            "type": step.get("type") or "tool",
            "tool_id": step.get("tool_id"),
            "tool_version": step.get("tool_version"),
            "label": step.get("label") or step.get("name"),
            "annotation": step.get("annotation") or "",
            "inputs": _step_inputs(step),
            "workflow_outputs": [o.get("label") or o.get("output_name")
                                 for o in (step.get("workflow_outputs") or [])],
        })
    creators = [c.get("name") for c in (ga.get("creator") or []) if isinstance(c, dict) and c.get("name")]
    return {
        "name": ga.get("name") or "Galaxy workflow",
        "annotation": ga.get("annotation") or "",
        "uuid": ga.get("uuid"),
        "license": ga.get("license"),
        "creators": creators,
        "tags": [t for t in (ga.get("tags") or []) if isinstance(t, str)],
        "format_version": ga.get("format-version"),
        "file": os.path.basename(file_path) if file_path else None,
        "local_path": _relative(file_path, crate_dir) if file_path else None,
        "steps": steps,
    }


def _relative(path, crate_dir) -> str:
    if crate_dir:
        try:
            return os.path.relpath(path, crate_dir)
        except ValueError:
            pass
    return os.path.basename(str(path))


# ---- the model store ---------------------------------------------------------------

def _ids(mapping: dict) -> list[str]:
    """``{"input1": ["id", ...], ...}`` -> the ids, in mapping order, unique."""
    out = []
    for values in (mapping or {}).values():
        for value in values if isinstance(values, list) else [values]:
            if value and value not in out:
                out.append(value)
    return out


def clean_params(params) -> dict:
    """Tool params minus Galaxy's bookkeeping (``__*`` keys, chromInfo,
    dbkey) and minus dataset references (they are usedDataset edges)."""
    def is_ref(value):
        return isinstance(value, dict) and "values" in value and isinstance(value["values"], list) \
            and all(isinstance(v, dict) and "src" in v for v in value["values"])

    def clean(value):
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if str(k).startswith("__") or k in ("chromInfo", "dbkey") or is_ref(v):
                    continue
                cleaned = clean(v)
                if cleaned not in (None, {}, []):
                    out[k] = cleaned
            return out
        if isinstance(value, list):
            return [c for c in (clean(v) for v in value) if c not in (None, {}, [])]
        return value

    if not isinstance(params, dict):
        return {}
    params = dict(params)
    # An upload (__DATA_FETCH__) carries its real request as a JSON string
    # and a temp-file path; unpack the former, drop the latter.
    if isinstance(params.get("request_json"), str):
        try:
            params["request"] = json.loads(params.pop("request_json"))
        except ValueError:
            pass
    params.pop("files", None)
    params.pop("paramfile", None)
    return clean(params)


def dataset_key(hda: dict) -> str:
    """What makes two HDAs the same dataset: the underlying dataset's uuid,
    else the file it points at, else the HDA itself."""
    return hda.get("dataset_uuid") or hda.get("file_name") or hda["encoded_id"]


def read_store(store: str, crate_dir=None) -> dict:
    invocations = _read_json(os.path.join(store, "invocation_attrs.txt"), [])
    if not invocations:
        raise ValueError(f"{store}: invocation_attrs.txt holds no invocation")
    inv = invocations[0]
    jobs_raw = _read_json(os.path.join(store, "jobs_attrs.txt"), [])
    datasets_raw = _read_json(os.path.join(store, "datasets_attrs.txt"), [])
    collections_raw = _read_json(os.path.join(store, "collections_attrs.txt"), [])
    export_attrs = _read_json(os.path.join(store, "export_attrs.txt"), {}) or {}

    # the workflow
    workflow = None
    wf_dir = os.path.join(store, "workflows")
    if os.path.isdir(wf_dir):
        ga_files = sorted(f for f in os.listdir(wf_dir) if f.endswith(".ga"))
        preferred = [f for f in ga_files if f.startswith(str(inv.get("workflow") or ""))] or ga_files
        if preferred:
            ga_path = os.path.join(wf_dir, preferred[0])
            workflow = workflow_record(read_ga(ga_path), ga_path, crate_dir)

    # steps: which job belongs to which step, and what each step put out
    steps = []
    job_step = {}
    for step in inv.get("steps") or []:
        job_id = (step.get("job") or {}).get("encoded_id")
        index = step.get("order_index")
        ga_step = (workflow["steps"][index] if workflow and index is not None
                   and index < len(workflow["steps"]) else {})
        steps.append({
            "index": index,
            "label": ga_step.get("label"),
            "type": ga_step.get("type"),
            "tool_id": ga_step.get("tool_id"),
            "state": step.get("state"),
            "job_id": job_id,
            "outputs": _ids({o["output_name"]: [o["dataset"]["encoded_id"]]
                             for o in step.get("outputs") or [] if o.get("dataset")}),
            "output_collections": _ids({o["output_name"]: [o["dataset_collection"]["encoded_id"]]
                                        for o in step.get("output_collections") or []
                                        if o.get("dataset_collection")}),
        })
        if job_id:
            job_step[job_id] = index

    def labelled(entries, key):
        out = []
        for e in entries or []:
            ref = e.get(key) or {}
            if ref.get("encoded_id"):
                wo = e.get("workflow_output") or {}
                out.append({"id": ref["encoded_id"], "label": wo.get("label") or wo.get("output_name")})
        return out

    galaxy_versions = sorted({j.get("galaxy_version") for j in jobs_raw if j.get("galaxy_version")})
    invocation_uuid = next((j["params"].get("__workflow_invocation_uuid__")
                            for j in jobs_raw if isinstance(j.get("params"), dict)
                            and j["params"].get("__workflow_invocation_uuid__")), None)
    param_labels = {s["index"]: s["label"] for s in steps}
    invocation = {
        "encoded_id": inv.get("encoded_id"),
        "uuid": invocation_uuid,
        "state": inv.get("state"),
        "create_time": inv.get("create_time"),
        "update_time": inv.get("update_time"),
        "workflow_id": inv.get("workflow"),
        "galaxy_version": galaxy_versions[-1] if galaxy_versions else None,
        "export_version": export_attrs.get("galaxy_export_version"),
        "steps": steps,
        "input_datasets": [d["dataset"]["encoded_id"] for d in inv.get("input_datasets") or []
                           if d.get("dataset")],
        "input_collections": [d["dataset_collection"]["encoded_id"]
                              for d in inv.get("input_dataset_collections") or []
                              if d.get("dataset_collection")],
        "input_parameters": [{"label": param_labels.get(p.get("order_index")) or str(p.get("order_index")),
                              "value": p.get("parameter_value")}
                             for p in inv.get("input_step_parameters") or []],
        "output_datasets": labelled(inv.get("output_datasets"), "dataset"),
        "output_collections": labelled(inv.get("output_dataset_collections"), "dataset_collection"),
    }

    jobs = []
    for j in jobs_raw:
        jobs.append({
            "encoded_id": j["encoded_id"],
            "tool_id": j.get("tool_id"),
            "tool_version": j.get("tool_version"),
            "state": j.get("state"),
            "exit_code": j.get("exit_code"),
            "create_time": j.get("create_time"),
            "command_line": j.get("command_line") or "",
            "params": clean_params(j.get("params")),
            "inputs": _ids(j.get("input_dataset_mapping")),
            "input_collections": _ids(j.get("input_dataset_collection_mapping")),
            "outputs": _ids(j.get("output_dataset_mapping")),
            "output_collections": _ids(j.get("output_dataset_collection_mapping"))
                                  + [i for i in _ids(j.get("implicit_output_dataset_collection_mapping"))
                                     if i not in _ids(j.get("output_dataset_collection_mapping"))],
            "step_index": job_step.get(j["encoded_id"]),
        })
    jobs.sort(key=lambda j: (j["create_time"] or "", j["encoded_id"]))

    datasets = []
    for d in datasets_raw:
        local = None
        if d.get("file_name") and os.path.exists(os.path.join(store, d["file_name"])):
            local = _relative(os.path.join(store, d["file_name"]), crate_dir) if crate_dir else d["file_name"]
        hashes = {h.get("hash_function", "").lower(): h.get("hash_value")
                  for h in (d.get("hashes") or []) if isinstance(h, dict)}
        datasets.append({
            "encoded_id": d["encoded_id"],
            "key": dataset_key(d),
            "name": d.get("name") or d["encoded_id"],
            "extension": d.get("extension") or "data",
            "state": d.get("state"),
            "create_time": d.get("create_time"),
            "file_name": d.get("file_name"),
            "local_path": local,
            "size": d.get("size") or (d.get("file_metadata") or {}).get("size"),
            "hashes": hashes,
            "hid": d.get("hid"),
            "blurb": d.get("blurb") or "",
            "info": d.get("info") or "",
            "uuid": d.get("dataset_uuid"),
            # the HDAs this one was copied from (in the source history); a job
            # that made the original is the job that made this file
            "copy_chain": [i for i in (d.get("copied_from_history_dataset_association_id_chain") or []) if i],
            "deleted": bool(d.get("deleted")),
            "visible": d.get("visible", True),
        })

    collections = []
    for c in collections_raw:
        coll = c.get("collection") or {}
        elements = []
        for e in coll.get("elements") or []:
            if e.get("hda"):
                elements.append({"identifier": e.get("element_identifier"),
                                 "dataset": e["hda"]["encoded_id"]})
            elif e.get("child_collection"):
                elements.append({"identifier": e.get("element_identifier"),
                                 "collection": e["child_collection"]["encoded_id"]})
        collections.append({
            "encoded_id": c["encoded_id"],
            "name": c.get("display_name") or c["encoded_id"],
            "type": coll.get("type"),
            "state": c.get("state"),
            "hid": c.get("hid"),
            "copy_chain": [i for i in (c.get("copied_from_history_dataset_collection_association_id_chain") or []) if i],
            "elements": elements,
        })

    return {"invocation": invocation, "workflow": workflow, "jobs": jobs,
            "datasets": datasets, "collections": collections}


# ---- the Galaxy API -----------------------------------------------------------------

def download_invocation_export(url: str, api_key: str, invocation_id: str,
                               timeout: float = 600.0) -> str:
    """Ask a Galaxy server for an invocation's model store and return the
    downloaded archive path (POST prepare_store_download, poll the short
    term storage until ready, GET it)."""
    import urllib.request

    base = url.rstrip("/")
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req) as resp:
            return resp.read()

    reply = json.loads(call("POST", f"/api/invocations/{invocation_id}/prepare_store_download",
                            {"model_store_format": "tgz", "include_files": False,
                             "include_hidden": True, "include_deleted": False}))
    sts_id = reply["storage_request_id"]
    deadline = time.time() + timeout
    while json.loads(call("GET", f"/api/short_term_storage/{sts_id}/ready")) is not True:
        if time.time() > deadline:
            raise TimeoutError(f"Galaxy did not finish exporting invocation {invocation_id}")
        time.sleep(2)
    target = os.path.join(tempfile.mkdtemp(prefix="galaxy-api-"), f"invocation-{invocation_id}.tgz")
    with open(target, "wb") as f:
        f.write(call("GET", f"/api/short_term_storage/{sts_id}"))
    return target


# ---- entry point --------------------------------------------------------------------

def extract(source, *, api_key=None, invocation_id=None, naan=DEFAULT_NAAN, name=None,
            description=None, author=None, keywords=None, license=None, version="1.0",
            date_published=None, crate_dir=None) -> dict:
    """Read a Galaxy export and return the records ``convert`` maps.

    ``source``: an export archive, an unpacked export folder, a ``.ga``
    file, or a Galaxy URL (with ``api_key`` and ``invocation_id``).
    """
    source = str(source)
    if source.startswith(("http://", "https://")):
        if not (api_key and invocation_id):
            raise ValueError("a Galaxy URL needs api_key= and invocation_id=")
        store = unpack(download_invocation_export(source, api_key, invocation_id))
        data = read_store(store, crate_dir)
    elif source.endswith(".ga"):
        data = {"invocation": None, "workflow": workflow_record(read_ga(source), source, crate_dir),
                "jobs": [], "datasets": [], "collections": []}
    elif os.path.isfile(source) and source.endswith(ARCHIVE_SUFFIXES):
        data = read_store(unpack(source), crate_dir)
    else:
        data = read_store(find_store(source), crate_dir)

    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    wf = data["workflow"] or {}
    inv = data["invocation"]
    title = name or wf.get("name") or f"Galaxy invocation {inv['encoded_id']}" if (name or wf or inv) else "Galaxy workflow"
    when = (inv or {}).get("create_time") or ""
    tools = sorted({(j["tool_id"], j["tool_version"] or "") for j in data["jobs"] if j.get("tool_id")}
                   | {(s["tool_id"], s["tool_version"] or "") for s in wf.get("steps", [])
                      if s.get("type") == "tool" and s.get("tool_id")})
    data.update({
        "settings": {
            "naan": naan,
            "name": title,
            "description": description or wf.get("annotation") or (
                f"Galaxy workflow '{title}'" + (" and one invocation of it" if inv else "")),
            "author": author or ", ".join(wf.get("creators") or []),
            "keywords": keywords or (["galaxy", "workflow"] + (["invocation"] if inv else [])
                                     + list(wf.get("tags") or [])),
            "license": license or wf.get("license") or "https://spdx.org/licenses/CC-BY-4.0",
            "version": version,
            "date_published": date_published or when[:10] or date.today().isoformat(),
        },
        "tools": [{"tool_id": t, "tool_version": v} for t, v in tools],
    })
    return data
