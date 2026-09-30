"""EVI Schema nodes for the data files a run produced.

The inference itself — reading a CSV/TSV/Parquet header and sampling its
columns, an HDF5 file's datasets, a WFDB record, a DICOM header — is
``fairscape_models.schema``: ``infer_schema`` dispatches on the extension and
the per-format readers are optional extras of that package
(``pip install "fairscape-models[schema-infer]"``). This module is the part
the workflow importers share and that ``fairscape_models`` must not know
about: which files count, the deterministic ARK a Schema gets so re-running
a conversion mints the same identifiers, and the plain-dict node the plugins
map. It replaces the three copies of that loop that used to import the
inference from ``fairscape_cli.models.schema``.

    from fairscape_conversion.core.schemas import supported, schema_node

    if supported(path):
        node = schema_node(abs_path, naan=naan, display_path=path,
                           dataset_source=source, tool="cromwell-fairscape")
        if node:
            schemas[path] = node
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from .arks import mint_ark

INSTALL = 'pip install "fairscape-conversion[schemas]"'

#: Every note this module printed since the last :func:`reset_notes` — for a
#: caller that shows its own run log (the studio does) to repeat them there.
NOTES: list = []
_warned: set = set()


def _skipped(key: str, why: str) -> None:
    """Say once, on stderr and in :data:`NOTES`, that schemas were skipped and
    what to run to get them."""
    if key in _warned:
        return
    _warned.add(key)
    message = f"Schema inference skipped: {why}. To infer schemas run: {INSTALL}"
    NOTES.append(message)
    print(message, file=sys.stderr)


def reset_notes() -> None:
    """Forget what has been said, so the next run reports again."""
    NOTES.clear()
    _warned.clear()


def extension(path: str) -> str:
    return os.path.splitext(str(path).rstrip("/"))[1].lower().lstrip(".")


def supported(path: str) -> bool:
    """Does ``fairscape_models`` know how to infer a schema for this file name?

    False, with one note, when ``fairscape_models.schema`` itself is missing
    (an old release); a missing per-format reader is only found out when the
    file is read, because the readers are lazy imports.
    """
    try:
        from fairscape_models.schema.registry import EXTENSION_MAP
    except ImportError:
        _skipped("registry", "this fairscape-models has no fairscape_models.schema.registry")
        return False
    return extension(path) in EXTENSION_MAP


def schema_ark(naan: str, name: str, dataset_source: str) -> str:
    """The Schema's ARK, hashed from the ARK of the Dataset it describes, so it
    is stable across re-runs and distinct from the Dataset's own."""
    dataset_ark = mint_ark(naan, "dataset", name, dataset_source)
    return mint_ark(naan, "schema", name, dataset_ark)


def schema_node(abs_path: str, *, naan: str, display_path: str,
                dataset_source: str, tool: str,
                description: Optional[str] = None) -> Optional[dict]:
    """Infer one EVI Schema node for the file at ``abs_path``.

    ``display_path`` is how the run referred to the file (what the Dataset's
    name is taken from and what the description quotes); ``dataset_source``
    is the stable string the Dataset's ARK was minted from, so the Schema's
    ARK follows it. ``tool`` names the importer in the description.

    Returns the node as a plain dict, or None when the file cannot be read
    (a WARNING naming the file) or its format's reader is not installed (one
    "Schema inference skipped … To infer schemas run: …" note per format,
    on stderr and in :data:`NOTES`).
    """
    try:
        from fairscape_models.schema.registry import infer_schema
    except ImportError:
        _skipped("registry", "this fairscape-models has no fairscape_models.schema.registry")
        return None

    name = os.path.basename(str(display_path).rstrip("/")) or str(display_path)
    ext = extension(display_path) or extension(abs_path)
    try:
        model = infer_schema(
            abs_path,
            name=f"Schema for {name}",
            description=description or (f"Schema inferred from the {ext} file "
                                        f"'{display_path}' by {tool}"),
            guid=schema_ark(naan, name, dataset_source))
    except ImportError as e:
        # a per-format reader (frictionless, h5py, wfdb, pydicom) is missing
        _skipped(f"reader:{ext}", f"the reader for .{ext} files is not installed ({e})")
        return None
    except Exception as e:  # noqa: BLE001 — one bad file must not sink the run
        print(f"WARNING: schema inference failed for '{display_path}': {e}",
              file=sys.stderr)
        return None
    return model.model_dump(by_alias=True, exclude_none=True)
