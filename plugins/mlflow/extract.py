"""mlflow plugin extraction — MLflow tracking store -> plain records.

This is the I/O half of the conversion: everything that talks to the tracking
store or touches the filesystem happens here, so the mapping itself
(``convert("import", records)``) stays a pure function and the golden-file
test stays hermetic. Mirrors ``plugins/cromwell/extract.py``.

MLflow has no run-completion hook (its plugin points are stores/context
providers, none fire at ``end_run``), so this is a post-hoc exporter over the
``MlflowClient`` read API. That makes it work against ANY tracking backend —
a local ``mlruns`` directory (the deprecated FileStore; ``extract`` sets
``MLFLOW_ALLOW_FILE_STORE`` for you), ``sqlite:///mlflow.db``, or a remote
``http(s)://`` tracking server.

Facts about MLflow this relies on (verified against MLflow 3.15):
- nested runs carry the system tag ``mlflow.parentRunId``;
- source identity lives in the ``mlflow.source.name`` / ``mlflow.source.type``
  / ``mlflow.source.git.commit`` / ``mlflow.user`` system tags;
- logged dataset inputs (``mlflow.log_input``) expose name, a content-based
  digest, and a column spec (``mlflow_colspec``) — the colspec converts to an
  EVI Schema without reading any data file;
- MLflow 3 models are first-class LoggedModel entities found via
  ``search_logged_models`` and linked by ``source_run_id``; on MLflow 2.x
  stores the same information is in the ``mlflow.log-model.history`` run tag
  and the model files live under the run's artifact tree (this extractor
  handles both).

ARK-source note: unlike Cromwell (where re-running a workflow is conceptually
the same computation, so ARK sources strip the run UUID), an MLflow run is a
unique tracked event — re-training is a genuinely different run. The
determinism contract here is: exporting the same tracking store twice yields
byte-identical ARKs, so run-scoped ARK sources include the run_id.
"""

from __future__ import annotations

import getpass
import json
import os
from datetime import datetime, timezone

from ...core.arks import mint_ark, slugify

REMOTE_SCHEMES = ("http://", "https://", "git://", "ssh://", "gs://", "s3://",
                  "wasbs://", "dbfs://", "ftp://")

# mlflow colspec DataType -> JSON-Schema type (fairscape Property.type)
COLSPEC_TYPES = {
    "boolean": "boolean",
    "integer": "integer",
    "long": "integer",
    "float": "number",
    "double": "number",
    "string": "string",
    "binary": "string",
    "datetime": "string",
}


def _iso(epoch_ms):
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000,
                                  timezone.utc).astimezone().isoformat()


def _client(tracking_uri):
    """Build an MlflowClient, normalizing a bare mlruns directory path to a
    file:// URI (and opting in to MLflow 3's deprecated-but-working FileStore)."""
    try:
        import mlflow
        from mlflow.tracking import MlflowClient
    except ImportError as e:
        raise ImportError(
            "mlflow-fairscape extraction reads the tracking store through the "
            "mlflow client; pip install mlflow (the conversion itself — "
            "convert('import', records) — has no mlflow dependency)") from e
    uri = str(tracking_uri)
    if "://" not in uri and not uri.startswith("file:"):
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        uri = "file://" + os.path.abspath(uri)
    elif uri.startswith("file:"):
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    # module-level helpers (mlflow.artifacts.download_artifacts) read the
    # global tracking URI, not the client's — keep the two in sync
    mlflow.set_tracking_uri(uri)
    return mlflow, MlflowClient(tracking_uri=uri)


def _search_all_runs(client, experiment_id):
    runs, token = [], None
    while True:
        page = client.search_runs([experiment_id], max_results=1000,
                                  order_by=["attributes.start_time ASC"],
                                  page_token=token)
        runs.extend(page)
        token = getattr(page, "token", None)
        if not token:
            return runs


def _walk_artifacts(client, run_id, path=None):
    for fi in client.list_artifacts(run_id, path):
        if fi.is_dir:
            yield from _walk_artifacts(client, run_id, fi.path)
        else:
            yield fi


def _local_artifact_root(artifact_uri):
    """file:///path -> /path; anything else -> None."""
    if artifact_uri.startswith("file://"):
        return artifact_uri[len("file://"):]
    if artifact_uri.startswith("/"):
        return artifact_uri
    return None


def _logged_models(client, experiment_id, runs):
    """MLflow 3 LoggedModels for the experiment, grouped by source run; falls
    back to the 2.x ``mlflow.log-model.history`` run tag. Returns
    ``{model_id: raw}`` where raw carries name/flavors/run_id/artifact
    location and, for 2.x, the run-artifact subtree the model occupies."""
    models = {}
    try:
        page = client.search_logged_models(experiment_ids=[experiment_id])
        entries = list(page)
        while getattr(page, "token", None):
            page = client.search_logged_models(experiment_ids=[experiment_id],
                                               page_token=page.token)
            entries.extend(page)
        for m in entries:
            # MLflow 3 links metrics/params directly to the LoggedModel —
            # the model-scoped copy that stays unambiguous when one run
            # logs several models
            metrics = {}
            for met in (getattr(m, "metrics", None) or []):
                metrics[met.key] = met.value
            models[m.model_id] = {
                "model_id": m.model_id,
                "name": m.name,
                "run_id": m.source_run_id,
                "artifact_location": getattr(m, "artifact_location", None),
                "run_subtree": None,
                "params": dict(getattr(m, "params", None) or {}),
                "metrics": metrics,
            }
        return models
    except Exception:
        pass  # pre-3.x server/store: no LoggedModel entity

    for run in runs:
        history = run.data.tags.get("mlflow.log-model.history")
        if not history:
            continue
        try:
            entries = json.loads(history)
        except ValueError:
            continue
        for entry in entries:
            model_id = entry.get("model_uuid") or (
                run.info.run_id + ":" + entry.get("artifact_path", "model"))
            models[model_id] = {
                "model_id": model_id,
                "name": entry.get("artifact_path", "model"),
                "run_id": run.info.run_id,
                "artifact_location": None,
                "run_subtree": entry.get("artifact_path"),
                "flavors": sorted((entry.get("flavors") or {})),
                "mlflow_version": entry.get("mlflow_version"),
            }
    return models


def _model_inputs(client, run, known_models):
    """Model ids a run declared as inputs (MLflow 3 ``log_input(model=...)``).
    ``search_runs`` leaves ``inputs.model_inputs`` empty on the SQL store
    (verified against MLflow 3.16) while ``get_run`` fills it, so re-fetch
    the run when the search result shows none. Pre-3 stores have no such
    attribute and yield []."""
    def ids_of(r):
        inputs = getattr(r, "inputs", None)
        return [m.model_id
                for m in (getattr(inputs, "model_inputs", None) or [])]
    ids = ids_of(run)
    if not ids:
        try:
            ids = ids_of(client.get_run(run.info.run_id))
        except Exception:
            ids = []
    return [m for m in ids if m in known_models]


def _model_meta_from_dir(model_dir):
    """Read flavor + mlflow_version from a model directory's MLmodel file."""
    mlmodel = os.path.join(model_dir, "MLmodel")
    if not os.path.isfile(mlmodel):
        return None, None
    try:
        import yaml  # a hard mlflow dependency, so present here
        with open(mlmodel) as f:
            doc = yaml.safe_load(f) or {}
    except Exception:
        return None, None
    flavors = [f for f in (doc.get("flavors") or {}) if f != "python_function"]
    flavor = flavors[0] if flavors else (
        "python_function" if doc.get("flavors") else None)
    return flavor, doc.get("mlflow_version")


def _dir_size(path):
    total = 0
    for base, _dirs, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(base, n))
            except OSError:
                pass
    return total or None


def _alias_dataset_inputs(runs, datasets, files):
    """Best-effort cross-run linking. A logged dataset input whose local
    source file is an artifact that *another* run logged (same basename,
    and the same size when the local file is still around) is that
    artifact: point the consuming run's usedDataset at the artifact's
    Dataset node instead of minting a second, producer-less node. This is
    what turns a chain of runs (prepare -> train -> evaluate) into one
    connected provenance graph. Ambiguous basenames are left alone."""
    by_basename = {}
    for key, info in files.items():
        by_basename.setdefault(os.path.basename(info["path"]), []).append(key)

    aliased = {}
    for key, ds in datasets.items():
        uri = ds.get("source_uri")
        if ds.get("source_type") != "local" or not uri:
            continue
        path = uri[len("file://"):] if uri.startswith("file://") else uri
        candidates = by_basename.get(os.path.basename(path), [])
        if os.path.isfile(path):
            size = os.path.getsize(path)
            candidates = [k for k in candidates
                          if files[k]["size"] in (None, size)]
        if len(candidates) == 1:
            aliased[key] = candidates[0]

    for run in runs:
        for di in run["dataset_inputs"]:
            file_key = aliased.get(di["key"])
            if file_key and files[file_key]["run_id"] != run["run_id"]:
                di["file_key"] = file_key

    still_direct = {di["key"] for run in runs for di in run["dataset_inputs"]
                    if not di.get("file_key")}
    for key in list(aliased):
        if key not in still_direct:
            del datasets[key]


def colspec_schema_node(dataset, naan):
    """Build an EVI Schema node from a logged dataset's mlflow_colspec —
    the same shape fairscape's TabularSchema dumps, minus the file-format
    claims (separator/header) we cannot make about an in-memory dataframe."""
    columns = dataset.get("columns") or []
    if not columns:
        return None
    dataset_ark = mint_ark(naan, "dataset", dataset["name"],
                           dataset["ark_source"])
    schema_ark = mint_ark(naan, "schema", dataset["name"], dataset_ark)
    properties, required = {}, []
    for i, col in enumerate(columns):
        properties[col["name"]] = {
            "description": (f"Column '{col['name']}' of MLflow dataset "
                            f"'{dataset['name']}' ({col['type']})"),
            "index": i,
            "type": COLSPEC_TYPES.get(col["type"], "string"),
        }
        if col.get("required"):
            required.append(col["name"])
    return {
        "@id": schema_ark,
        "@context": {"@vocab": "https://schema.org/",
                     "evi": "https://w3id.org/EVI#"},
        "@type": "evi:Schema",
        "name": f"Schema for MLflow dataset '{dataset['name']}'",
        "description": (f"Schema derived from the column spec MLflow logged "
                        f"for dataset '{dataset['name']}' "
                        f"(digest {dataset.get('digest')})"),
        "conformsTo": {"@id": "https://json-schema.org/draft/2020-12/schema"},
        "properties": properties,
        "type": "object",
        "additionalProperties": True,
        "required": required,
    }


def infer_file_schemas(files, naan, crate_dir):
    """Infer an EVI Schema node per copied artifact with a supported extension.
    Same fairscape-cli delegation and deterministic-ARK override as the
    cromwell/snakemake integrations."""
    try:
        from fairscape_cli.models.schema import infer_schema
        from fairscape_models.schema.registry import EXTENSION_MAP
    except ImportError:
        print("NOTE: fairscape-cli not importable; skipping schema inference")
        return {}

    schemas = {}
    for key in sorted(files):
        info = files[key]
        if info["locator"] != "contentUrl":
            continue
        ext = os.path.splitext(info["path"])[1].lower().lstrip(".")
        if ext not in EXTENSION_MAP:
            continue
        abs_p = os.path.join(crate_dir, info["locator_value"])
        if not os.path.isfile(abs_p):
            continue
        name = os.path.basename(info["path"])
        dataset_ark = mint_ark(naan, "dataset", name, info["ark_source"])
        schema_ark = mint_ark(naan, "schema", name, dataset_ark)
        try:
            model = infer_schema(
                abs_p,
                name=f"Schema for {name}",
                description=(f"Schema inferred from the {ext} artifact "
                             f"'{info['path']}' by mlflow-fairscape"),
                guid=schema_ark)
            schemas[f"file:{key}"] = model.model_dump(by_alias=True,
                                                      exclude_none=True)
        except Exception as e:
            print(f"WARNING: schema inference failed for '{info['path']}': {e}")
    return schemas


def extract(tracking_uri, experiment=None, run_id=None, crate_dir=None,
            naan="59853", name=None, description=None, author=None,
            keywords=None, license="https://spdx.org/licenses/CC-BY-4.0",
            crate_version="1.0", date_published=None, copy_artifacts=True,
            schemas=False):
    """MLflow tracking store -> the plain records dict the plugin maps.

    ``tracking_uri`` is any MLflow tracking URI (or a bare ``mlruns``
    directory path). Scope the export with ``experiment`` (name or id — all
    its runs) or ``run_id`` (that run plus its nested children).
    ``copy_artifacts=True`` downloads run artifacts and model directories
    into ``crate_dir`` (one folder per run) so the crate is self-contained;
    otherwise Datasets reference the tracking store via localPath.
    ``date_published`` pins the crate timestamp — pass it for reproducible
    output. ``schemas=True`` additionally infers an EVI Schema per copied
    data artifact (needs fairscape-cli importable); colspec Schemas for
    logged dataset inputs are always emitted.
    """
    mlflow, client = _client(tracking_uri)

    if run_id:
        exp_id = client.get_run(run_id).info.experiment_id
        exp = client.get_experiment(exp_id)
    elif experiment is not None:
        exp = client.get_experiment_by_name(str(experiment))
        if exp is None:
            try:
                exp = client.get_experiment(str(experiment))
            except Exception:
                raise ValueError(f"no MLflow experiment named or id'd "
                                 f"'{experiment}' in {tracking_uri}")
    else:
        candidates = [e for e in client.search_experiments()
                      if e.name != "Default"]
        if len(candidates) != 1:
            raise ValueError(
                "pass experiment=<name> or run_id=<id>; the store has "
                f"{len(candidates)} non-default experiments: "
                + ", ".join(sorted(e.name for e in candidates)))
        exp = candidates[0]

    all_runs = _search_all_runs(client, exp.experiment_id)
    if run_id:
        keep, frontier = set(), {run_id}
        while frontier:
            keep |= frontier
            frontier = {r.info.run_id for r in all_runs
                        if r.data.tags.get("mlflow.parentRunId") in frontier
                        and r.info.run_id not in keep}
        all_runs = [r for r in all_runs if r.info.run_id in keep]
    if not all_runs:
        raise ValueError(f"experiment '{exp.name}' has no runs to export")

    crate_dir = os.path.abspath(crate_dir or ".")
    if copy_artifacts:
        os.makedirs(crate_dir, exist_ok=True)

    exp_key = f"mlflow:{exp.name}"
    raw_models = _logged_models(client, exp.experiment_id, all_runs)
    models_by_run = {}
    for mid, m in raw_models.items():
        models_by_run.setdefault(m["run_id"], []).append(mid)

    runs, sources, datasets, files, models = [], {}, {}, {}, {}
    engine_version = None

    for r in all_runs:
        rid = r.info.run_id
        tags = dict(r.data.tags)
        run_name = tags.get("mlflow.runName") or r.info.run_name or rid[:8]
        run_dir_rel = f"{slugify(run_name)}-{rid[:8]}"

        source_key = None
        source_name = tags.get("mlflow.source.name")
        if source_name:
            commit = tags.get("mlflow.source.git.commit")
            source_key = f"{source_name}@{commit or 'local'}"
            sources.setdefault(source_key, {
                "key": source_key,
                "name": source_name,
                "source_type": tags.get("mlflow.source.type"),
                "git_commit": commit,
                "ark_source": source_key,
            })

        # ---- logged dataset inputs (experiment-scoped entities) ----
        dataset_inputs = []
        for di in getattr(r, "inputs", None) and r.inputs.dataset_inputs or []:
            ds = di.dataset
            key = f"{ds.name}@{ds.digest}"
            context = next((t.value for t in (di.tags or [])
                            if t.key == "mlflow.data.context"), None)
            if key not in datasets:
                columns, num_rows, num_elements, source_uri = [], None, None, None
                try:
                    spec = json.loads(ds.schema) if ds.schema else {}
                    for col in spec.get("mlflow_colspec", []):
                        columns.append({"name": col.get("name"),
                                        "type": col.get("type"),
                                        "required": col.get("required", True)})
                except ValueError:
                    pass
                try:
                    profile = json.loads(ds.profile) if ds.profile else {}
                    num_rows = profile.get("num_rows")
                    num_elements = profile.get("num_elements")
                except ValueError:
                    pass
                try:
                    source_uri = (json.loads(ds.source) if ds.source
                                  else {}).get("uri")
                except (ValueError, AttributeError):
                    pass
                datasets[key] = {
                    "key": key,
                    "name": ds.name,
                    "digest": ds.digest,
                    "source_type": ds.source_type,
                    "source_uri": source_uri,
                    "columns": columns,
                    "num_rows": num_rows,
                    "num_elements": num_elements,
                    "contexts": [],
                    "ark_source": f"mlflow-dataset:{key}",
                }
            if context and context not in datasets[key]["contexts"]:
                datasets[key]["contexts"].append(context)
            dataset_inputs.append({"key": key, "context": context})

        # ---- models used as inputs (MLflow 3: mlflow.log_input(model=...)) ----
        model_inputs = _model_inputs(client, r, raw_models)

        # ---- run artifacts ----
        local_root = _local_artifact_root(r.info.artifact_uri)
        downloaded_root = None
        if copy_artifacts:
            infos = list(_walk_artifacts(client, rid))
            if infos:
                downloaded_root = mlflow.artifacts.download_artifacts(
                    run_id=rid,
                    dst_path=os.path.join(crate_dir, run_dir_rel))
        else:
            infos = list(_walk_artifacts(client, rid))

        model_subtrees = [raw_models[m]["run_subtree"]
                          for m in models_by_run.get(rid, [])
                          if raw_models[m]["run_subtree"]]
        artifact_keys = []
        for fi in sorted(infos, key=lambda fi: fi.path):
            # 2.x: model files live in the run artifact tree; they belong to
            # the model Dataset, not to individual file Datasets
            if any(fi.path == sub or fi.path.startswith(sub + "/")
                   for sub in model_subtrees):
                continue
            key = f"{rid}:{fi.path}"
            info = {"key": key, "path": fi.path, "run_id": rid,
                    "size": fi.file_size,
                    "ark_source": f"{exp_key}#{rid}/{fi.path}"}
            if downloaded_root is not None:
                info["locator"] = "contentUrl"
                info["locator_value"] = f"{run_dir_rel}/{fi.path}"
            elif local_root:
                info["locator"] = "localPath"
                info["locator_value"] = os.path.join(local_root, fi.path)
            else:
                info["locator"] = "localPath"
                info["locator_value"] = r.info.artifact_uri + "/" + fi.path
            files[key] = info
            artifact_keys.append(key)

        # ---- logged models ----
        for mid in sorted(models_by_run.get(rid, [])):
            m = raw_models[mid]
            model_rec = {
                "model_id": mid,
                "name": m["name"],
                "run_id": rid,
                "flavor": None,
                "mlflow_version": m.get("mlflow_version"),
                "size": None,
                "params": m.get("params") or {},
                "metrics": m.get("metrics") or {},
                "ark_source": f"{exp_key}#{mid}",
            }
            if m.get("flavors"):
                non_pyfunc = [f for f in m["flavors"] if f != "python_function"]
                model_rec["flavor"] = (non_pyfunc or m["flavors"])[0]
            model_dir = None
            if copy_artifacts:
                dst = os.path.join(crate_dir, run_dir_rel)
                if m["run_subtree"]:
                    # 2.x model: already part of the run-artifact download
                    model_dir = os.path.join(dst, m["run_subtree"])
                    rel = f"{run_dir_rel}/{m['run_subtree']}"
                else:
                    model_dir = mlflow.artifacts.download_artifacts(
                        artifact_uri=f"models:/{mid}",
                        dst_path=os.path.join(dst, m["name"]))
                    rel = os.path.relpath(model_dir, crate_dir)
                model_rec["locator"] = "contentUrl"
                model_rec["locator_value"] = rel.rstrip("/") + "/"
                model_rec["size"] = _dir_size(model_dir)
            else:
                loc = m.get("artifact_location")
                if not loc and local_root and m["run_subtree"]:
                    loc = os.path.join(local_root, m["run_subtree"])
                model_rec["locator"] = "localPath"
                model_rec["locator_value"] = ((loc or f"models:/{mid}")
                                              .rstrip("/") + "/")
                local_loc = _local_artifact_root(loc or "")
                if local_loc and os.path.isdir(local_loc):
                    model_dir = local_loc
            if model_dir:
                flavor, ver = _model_meta_from_dir(model_dir)
                model_rec["flavor"] = model_rec["flavor"] or flavor
                model_rec["mlflow_version"] = (model_rec["mlflow_version"]
                                               or ver)
            engine_version = engine_version or model_rec["mlflow_version"]
            models[mid] = model_rec

        runs.append({
            "run_id": rid,
            "name": run_name,
            "ark_source": f"{exp_key}#{rid}",
            "parent_run_id": tags.get("mlflow.parentRunId"),
            "status": r.info.status,
            "user": tags.get("mlflow.user"),
            "source_key": source_key,
            "start_time": _iso(r.info.start_time),
            "end_time": _iso(r.info.end_time),
            "params": dict(r.data.params),
            "metrics": dict(r.data.metrics),
            "tags": {k: v for k, v in tags.items()
                     if not k.startswith("mlflow.")},
            "container": tags.get("mlflow.docker.image.name"),
            "dataset_inputs": dataset_inputs,
            "model_inputs": model_inputs,
            "artifacts": artifact_keys,
            "models": sorted(models_by_run.get(rid, [])),
        })

    engine_version = engine_version or mlflow.__version__
    _alias_dataset_inputs(runs, datasets, files)

    author = author or getpass.getuser()
    keyword_list = [k.strip() for k in (keywords or "").split(",") if k.strip()]
    scope = (f"run '{runs[0]['name']}'" if run_id
             else f"experiment '{exp.name}'")
    settings = {
        "naan": naan,
        "name": name or f"MLflow {scope}",
        "description": description
        or (f"FAIRSCAPE EVI RO-Crate describing MLflow {scope}, exported "
            "from the MLflow tracking store by mlflow-fairscape"),
        "author": author,
        "keywords": keyword_list or ["mlflow", "machine learning",
                                     "experiment tracking"],
        "license": license,
        "version": crate_version,
        "date_published": date_published
        or datetime.now(timezone.utc).astimezone().isoformat(),
    }

    schema_nodes = {}
    for key in sorted(datasets):
        node = colspec_schema_node(datasets[key], naan)
        if node:
            schema_nodes[f"dataset:{key}"] = node
    if schemas:
        schema_nodes.update(infer_file_schemas(files, naan, crate_dir))

    return {
        "settings": settings,
        "experiment": {
            "name": exp.name,
            "experiment_id": exp.experiment_id,
            "ark_source": exp_key + "#" + ",".join(
                sorted(r["run_id"] for r in runs)),
        },
        "engine": {"version": engine_version},
        "runs": runs,
        "sources": sources,
        "datasets": datasets,
        "models": models,
        "files": files,
        "schemas": schema_nodes,
    }
