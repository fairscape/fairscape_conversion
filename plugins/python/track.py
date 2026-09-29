"""track — run Python code and add what it did to a crate directory.

    python -m fairscape_conversion.core.cli track analysis.py [options] [-- script args]

Record (``record.py``) -> convert (the python plugin, plus the linked-crates
pass for ``--link-crate``) -> merge into ``CRATE_DIR/ro-crate-metadata.json``,
creating it on first use. Each run appends one Computation, the Software it
ran and its Datasets, so repeated runs (or notebook cells) build up one crate:

* an input the crate already describes — typically an earlier run's output —
  reuses that node (matched by file path; the latest one wins), so the
  provenance chain runs through the crate;
* a node whose ``@id`` is already there is not added again (identical code is
  one Software; a linked upstream crate appears once).

Code that is not already inside the crate directory is copied to
``software/<name>-<hash>.py`` there, so the crate keeps what ran.
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ...core.linking import _candidates, _canon, _find_root, _generated_by, _rewrite_refs
from . import convert
from .record import IOCapture, _now, build_record, code_hash, locate

METADATA = "ro-crate-metadata.json"


# ---------------------------------------------------------------------------
# crate on disk
# ---------------------------------------------------------------------------

def _read_crate(crate_dir: Path) -> Optional[Dict[str, Any]]:
    path = crate_dir / METADATA
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write_crate(crate_dir: Path, crate: Dict[str, Any]) -> None:
    crate_dir.mkdir(parents=True, exist_ok=True)
    (crate_dir / METADATA).write_text(json.dumps(crate, indent=2))


def crate_defaults(crate: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Author and keywords from an existing crate's root, to reuse by default."""
    if not crate:
        return {}
    root = _find_root(crate.get("@graph", []))
    out = {}
    if root.get("author"):
        out["author"] = root["author"]
    if root.get("keywords"):
        out["keywords"] = root["keywords"]
    return out


def start_clean(crate: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the metadata descriptor and root, with an empty ``hasPart``."""
    root = _find_root(crate["@graph"])
    descriptor = next(n for n in crate["@graph"] if n.get("@id") == METADATA)
    root["hasPart"] = []
    crate["@graph"] = [descriptor, root]
    return crate


def merge(existing: Optional[Dict[str, Any]], fragment: Dict[str, Any],
          crate_dir) -> Dict[str, Any]:
    """Append a converted run to the crate already in ``crate_dir``."""
    if existing is None:
        return fragment
    crate_dir = os.path.abspath(os.fspath(crate_dir))
    graph = existing["@graph"]
    root = _find_root(graph)
    known = {n.get("@id") for n in graph}

    by_path: Dict[str, str] = {}
    for node in graph:                       # later nodes win: the latest version
        for path in _candidates(node, [crate_dir]):
            by_path[_canon(path)] = node["@id"]

    frag_root = _find_root(fragment["@graph"])
    new_nodes, id_map = [], {}
    for node in fragment["@graph"]:
        nid = node.get("@id")
        if nid in (METADATA, frag_root.get("@id")) or nid in known:
            continue
        if not _generated_by(node):          # consumed: reuse what the crate has
            match = next((by_path[_canon(p)] for p in _candidates(node, [crate_dir])
                          if _canon(p) in by_path), None)
            if match:
                id_map[nid] = match
                continue
        new_nodes.append(node)
        known.add(nid)

    new_nodes = [_rewrite_refs(n, id_map) for n in new_nodes]
    graph.extend(new_nodes)
    has_part = root.get("hasPart") or []
    if not isinstance(has_part, list):
        has_part = [has_part]
    root["hasPart"] = has_part + [{"@id": n["@id"]} for n in new_nodes]
    return existing


# ---------------------------------------------------------------------------
# record + convert + merge
# ---------------------------------------------------------------------------

def _software_locator(code: str, name: str, script_path: Optional[Path],
                      crate_dir: Path) -> Dict[str, Any]:
    """Where the crate finds the code: in place when it is inside the crate
    directory, else a copy under ``software/``."""
    if script_path is not None:
        loc = locate(str(script_path.resolve()), str(crate_dir))
        if loc["locator"] == "contentUrl":
            return {"name": script_path.name, **loc}
    stem = Path(name).stem
    rel = f"software/{stem}-{code_hash(code)[:7]}.py"
    target = crate_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code)
    return {"name": script_path.name if script_path else f"{stem}.py",
            "locator": "contentUrl", "locator_value": rel}


def add_run(
    *,
    code: str,
    name: str,
    capture: IOCapture,
    crate_dir,
    starttime: str,
    endtime: str,
    script_path: Optional[Path] = None,
    argv: Optional[List[str]] = None,
    exit_code: int = 0,
    manual_inputs: Sequence[str] = (),
    author: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    link_crates: Sequence[str] = (),
    clean: bool = False,
) -> Optional[Dict[str, Any]]:
    """Convert one captured run and merge it into ``crate_dir``.

    Returns the Computation node that was added, or None when the run touched
    no files (nothing is written then).
    """
    crate_dir = Path(crate_dir).resolve()
    inputs = set(capture.inputs) | {str((crate_dir / p).resolve()) if not os.path.isabs(p)
                                     else p for p in manual_inputs}
    if not inputs and not capture.outputs:
        return None

    existing = _read_crate(crate_dir)
    if existing is not None and clean:
        existing = start_clean(existing)
    defaults = crate_defaults(existing)

    record = build_record(
        code=code, name=name,
        script=_software_locator(code, name, script_path, crate_dir),
        inputs=inputs, outputs=capture.outputs, crate_dir=crate_dir,
        starttime=starttime, endtime=endtime, argv=argv, exit_code=exit_code,
        author=author or defaults.get("author"),
        keywords=keywords or defaults.get("keywords"),
        crate_name=None if existing else f"Tracked computations in '{crate_dir.name}'",
        crate_description=None if existing else (
            "FAIRSCAPE RO-Crate of Python runs recorded with fairscape_conversion track"),
    )
    options = {"crate_dir": str(crate_dir)}
    if link_crates:
        options["linked_crates"] = list(link_crates)
    fragment = convert("import", record, **options)
    computation = next(n for n in fragment["@graph"]
                       if "https://w3id.org/EVI#Computation" in n.get("@type", []))
    _write_crate(crate_dir, merge(existing, fragment, crate_dir))
    return computation


def track_script(script, script_args: Sequence[str] = (), *, crate_dir=".",
                 name: Optional[str] = None, **options):
    """Run ``script`` as ``__main__`` (like ``python script args``) and add the
    run to ``crate_dir``. Returns ``(computation_node_or_None, exit_code)``."""
    script_path = Path(script).resolve()
    code = script_path.read_text()
    old_argv, old_path0 = sys.argv, sys.path[0] if sys.path else None
    sys.argv = [str(script_path), *script_args]
    sys.path.insert(0, str(script_path.parent))
    exit_code = 0
    starttime = _now()
    try:
        with IOCapture() as capture:
            try:
                runpy.run_path(str(script_path), run_name="__main__")
            except SystemExit as exc:
                exit_code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    finally:
        sys.argv = old_argv
        if sys.path and sys.path[0] == str(script_path.parent):
            sys.path.pop(0)
    computation = add_run(
        code=code, name=name or script_path.stem, capture=capture,
        crate_dir=crate_dir, starttime=starttime, endtime=_now(),
        script_path=script_path, argv=[script_path.name, *script_args],
        exit_code=exit_code, **options)
    return computation, exit_code


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fairscape_conversion track",
        usage="%(prog)s SCRIPT [options] [-- SCRIPT_ARGS ...]",
        description="Run a Python script and add the run (Computation, Software, "
                    "the Datasets it read and wrote) to an RO-Crate directory. "
                    "Everything after -- is passed to the script.")
    p.add_argument("script", help="the Python script to run")
    p.add_argument("--crate-dir", default=".",
                   help="crate directory to add the run to (default: current "
                        "directory; created if missing)")
    p.add_argument("--name", help="name for this run (default: the script's name)")
    p.add_argument("--author", help="default: the crate root's author, else your username")
    p.add_argument("--keyword", dest="keywords", action="append",
                   help="repeatable; default: the crate root's keywords")
    p.add_argument("--input", dest="manual_inputs", action="append", default=[],
                   help="an input the capture cannot see (repeatable)")
    p.add_argument("--link-crate", dest="link_crates", action="append", default=[],
                   help="an upstream crate whose entities this run's inputs reuse (repeatable)")
    p.add_argument("--start-clean", action="store_true",
                   help="drop everything but the root from the crate first")
    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    script_args: List[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, script_args = argv[:i], argv[i + 1:]
    args = _parser().parse_args(argv)
    if not Path(args.script).is_file():
        print(f"error: script not found: {args.script}", file=sys.stderr)
        return 1
    try:
        computation, exit_code = track_script(
            args.script, script_args, crate_dir=args.crate_dir, name=args.name,
            author=args.author, keywords=args.keywords,
            manual_inputs=args.manual_inputs, link_crates=args.link_crates,
            clean=args.start_clean)
    except Exception as exc:                      # the script itself failed
        print(f"error: {args.script} raised {type(exc).__name__}: {exc}", file=sys.stderr)
        print("nothing was recorded", file=sys.stderr)
        return 1
    if exit_code:
        print(f"warning: {args.script} exited with code {exit_code}", file=sys.stderr)
    if computation is None:
        print("no file I/O detected; nothing was recorded", file=sys.stderr)
        return exit_code or 0
    crate = Path(args.crate_dir) / METADATA
    print(f"{computation['@id']}  "
          f"({len(computation.get('usedDataset', []))} in, "
          f"{len(computation.get('generated', []))} out) -> {crate}")
    return exit_code or 0


if __name__ == "__main__":
    raise SystemExit(main())
