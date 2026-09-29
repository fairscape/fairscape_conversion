"""python plugin recording — run Python code and write down what it touched.

This is the I/O half of the conversion (like ``plugins/mlflow/extract.py``):
everything that executes code or touches the filesystem happens here, so the
mapping itself (``convert("import", record)``) stays a pure function and the
golden-file test stays hermetic.

:class:`IOCapture` patches the common file entry points while the code runs —
``open``, ``pathlib.Path``'s read/write helpers, and, when they are installed,
pandas' ``read_*``/``to_*``, numpy's ``load``/``save`` and matplotlib's
``savefig`` — and collects the paths read and written. :func:`build_record`
turns that into the plain run record the plugin converts.

What gets recorded, per file:

* a file both read and written in the same run is an output (an intermediate
  the code produced, not an input it was given);
* only regular files that exist after the run are kept;
* files inside the crate directory get a crate-relative ``contentUrl``;
  files outside it get an absolute ``localPath`` ("was here when this ran"),
  which is also what lets ``--link-crate`` find them in an upstream crate.
"""

from __future__ import annotations

import builtins
import getpass
import hashlib
import importlib.util
import os
import pathlib
import platform
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

from ...core.arks import DEFAULT_NAAN

#: Substrings that mark a path as tooling noise rather than research data.
EXCLUDED_PATTERNS = (
    ".matplotlib", ".ipython", ".jupyter", "site-packages", "__pycache__",
    "ro-crate-metadata.json",
)
#: Pseudo-filesystems and interpreter trees are never data.
EXCLUDED_PREFIXES = tuple({"/dev/", "/proc/", "/sys/",
                           os.path.join(sys.prefix, ""),
                           os.path.join(sys.base_prefix, "")})

_WRITE_MODES = ("w", "a", "x", "+")
#: Keyword names pandas / numpy / matplotlib use for the path argument.
_PATH_KWARGS = ("filepath_or_buffer", "path_or_buf", "path", "io", "excel_writer",
                "file", "fname")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _is_installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


class IOCapture:
    """Context manager that records the file paths code reads and writes."""

    def __init__(self, excluded_patterns: Iterable[str] = EXCLUDED_PATTERNS):
        self.excluded_patterns = tuple(p.lower() for p in excluded_patterns)
        self.inputs: Set[str] = set()
        self.outputs: Set[str] = set()
        self._restore: List[tuple] = []

    # ---- bookkeeping -------------------------------------------------------
    def _path(self, target) -> Optional[str]:
        """The absolute path for ``target``, or None for anything that is not a
        trackable filesystem path (file descriptors, buffers, excluded paths)."""
        if not isinstance(target, (str, os.PathLike)):
            return None
        path = os.path.abspath(os.fspath(target))
        if path.startswith(EXCLUDED_PREFIXES):
            return None
        if any(p in path.lower() for p in self.excluded_patterns):
            return None
        return path

    def read(self, target) -> None:
        path = self._path(target)
        if path:
            self.inputs.add(path)

    def wrote(self, target) -> None:
        path = self._path(target)
        if path:
            self.outputs.add(path)

    def opened(self, target, mode) -> None:
        mode = mode if isinstance(mode, str) else "r"
        if "r" in mode:
            self.read(target)
        if any(m in mode for m in _WRITE_MODES):
            self.wrote(target)

    def _patch(self, owner, attr, wrapper_factory) -> None:
        original = getattr(owner, attr)
        self._restore.append((owner, attr, original))
        setattr(owner, attr, wrapper_factory(original))

    # ---- patches -------------------------------------------------------------
    def _patch_open(self) -> None:
        capture = self

        def factory(original):
            def tracked_open(file, mode="r", *args, **kwargs):
                capture.opened(file, mode)
                return original(file, mode, *args, **kwargs)
            return tracked_open
        self._patch(builtins, "open", factory)

    def _patch_pathlib(self) -> None:
        capture = self
        Path = pathlib.Path

        def open_factory(original):
            def tracked(path, mode="r", *args, **kwargs):
                capture.opened(path, mode)
                return original(path, mode, *args, **kwargs)
            return tracked

        def reader(original):
            def tracked(path, *args, **kwargs):
                capture.read(path)
                return original(path, *args, **kwargs)
            return tracked

        def writer(original):
            def tracked(path, *args, **kwargs):
                capture.wrote(path)
                return original(path, *args, **kwargs)
            return tracked

        self._patch(Path, "open", open_factory)
        self._patch(Path, "read_text", reader)
        self._patch(Path, "read_bytes", reader)
        self._patch(Path, "write_text", writer)
        self._patch(Path, "write_bytes", writer)

    def _patch_path_arg(self, owner, names, record, *, method=False) -> None:
        """Patch callables whose path is the first argument (after ``self`` for
        a method, e.g. ``df.to_csv(path)``) or one of the usual keywords."""
        skip = 1 if method else 0

        def factory(original):
            def tracked(*args, **kwargs):
                if len(args) > skip:
                    record(args[skip])
                else:
                    record(next((kwargs[k] for k in _PATH_KWARGS if k in kwargs), None))
                return original(*args, **kwargs)
            return tracked
        for name in names:
            if hasattr(owner, name):
                self._patch(owner, name, factory)

    def _patch_libraries(self) -> None:
        """Patch pandas / numpy / matplotlib when installed. Runs before ``open``
        is patched, so the files these imports read are not recorded."""
        if _is_installed("pandas"):
            import pandas as pd
            self._patch_path_arg(pd, ("read_csv", "read_table", "read_excel",
                                      "read_parquet", "read_json", "read_feather",
                                      "read_pickle"), self.read)
            self._patch_path_arg(pd.DataFrame, ("to_csv", "to_excel", "to_parquet",
                                                "to_json", "to_feather", "to_pickle"),
                                 self.wrote, method=True)
        if _is_installed("numpy"):
            import numpy as np
            self._patch_path_arg(np, ("load", "loadtxt", "genfromtxt"), self.read)
            self._patch_path_arg(np, ("save", "savez", "savez_compressed", "savetxt"),
                                 self.wrote)
        if _is_installed("matplotlib"):
            # plt.savefig goes through Figure.savefig; importing pyplot here
            # would pick a backend before the code gets to.
            from matplotlib.figure import Figure
            self._patch_path_arg(Figure, ("savefig",), self.wrote, method=True)

    def __enter__(self):
        self._patch_libraries()
        self._patch_open()
        self._patch_pathlib()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for owner, attr, original in reversed(self._restore):
            setattr(owner, attr, original)
        self._restore.clear()
        return False


# ---------------------------------------------------------------------------
# run record
# ---------------------------------------------------------------------------

def _within(path: str, directory: str) -> bool:
    try:
        return os.path.commonpath([path, directory]) == directory
    except ValueError:
        return False


def locate(path: str, crate_dir: str) -> Dict[str, Any]:
    """``contentUrl`` (crate-relative) for a file inside the crate directory,
    else ``localPath`` (absolute)."""
    if _within(path, crate_dir):
        return {"locator": "contentUrl",
                "locator_value": os.path.relpath(path, crate_dir).replace(os.sep, "/")}
    return {"locator": "localPath", "locator_value": path}


def _file_entry(path: str, role: str, crate_dir: str) -> Dict[str, Any]:
    return {"role": role, "size": os.path.getsize(path), **locate(path, crate_dir)}


def code_hash(code: str) -> str:
    return hashlib.sha1(code.encode()).hexdigest()


def build_record(
    *,
    code: str,
    name: str,
    script: Dict[str, Any],
    inputs: Iterable[str],
    outputs: Iterable[str],
    crate_dir,
    starttime: str,
    endtime: str,
    argv: Optional[List[str]] = None,
    exit_code: int = 0,
    author: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    crate_name: Optional[str] = None,
    crate_description: Optional[str] = None,
    naan: str = DEFAULT_NAAN,
) -> Dict[str, Any]:
    """The plain run record the python plugin converts.

    ``script`` locates the code the run executed (``locator`` /
    ``locator_value``, as for files). ``inputs`` / ``outputs`` are absolute
    paths; see the module docstring for which ones are kept.
    """
    crate_dir = os.path.abspath(os.fspath(crate_dir))
    outputs = {os.path.abspath(p) for p in outputs if os.path.isfile(p)}
    inputs = {os.path.abspath(p) for p in inputs if os.path.isfile(p)} - outputs

    files = {}
    for path in sorted(inputs):
        files[path] = _file_entry(path, "input", crate_dir)
    for path in sorted(outputs):
        files[path] = _file_entry(path, "output", crate_dir)

    return {
        "settings": {
            "naan": naan,
            "name": crate_name or f"Python run of '{name}'",
            "description": crate_description or (
                f"FAIRSCAPE RO-Crate describing a tracked run of the Python code '{name}'"),
            "author": author or getpass.getuser(),
            "keywords": list(keywords or ["computation"]),
            "license": "https://spdx.org/licenses/CC-BY-4.0",
            "version": "1.0",
            "date_published": endtime,
        },
        "run": {
            "name": name,
            "script": script,
            "code_sha1": code_hash(code),
            "argv": list(argv or []),
            "python_version": platform.python_version(),
            "starttime": starttime,
            "endtime": endtime,
            "exit_code": exit_code,
        },
        "files": files,
    }
