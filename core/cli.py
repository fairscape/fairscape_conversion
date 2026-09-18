#!/usr/bin/env python3
"""Tiny CLI: ``fairscape_conversion convert <plugin> <import|export> <input> [output]``.

Reads JSON or YAML by extension, dispatches to the named plugin's ``convert``,
writes JSON (or YAML for a ``.yaml``/``.yml`` output path). The library API
(``fairscape_conversion.plugins.<name>.convert``) is what the tests and other code call; this
is only a convenience wrapper.

Five plugins IMPORT from a *path* rather than a parsed document — ``c2m2``
(the CFDE datapackage directory), ``frictionless`` (any Data Package directory
or datapackage.json), ``cpm`` (the crate plus the PROV bundle files its
metadata registers), ``redcap`` (the data dictionary CSV; ``--records FILE``
adds the record export) and ``galaxy`` (an invocation export archive or
folder, or a .ga file) — so their input path is passed through untouched.

``cpm`` export writes PROV-JSON by default; ``--provn`` writes PROV-N text
instead (both serializations the CPM RO-Crate profile allows).

``--link-crate DIR`` (repeatable) on any import runs the linked-crate pass
after the conversion: inputs that ``DIR``'s crate already describes reuse its
identifiers (see ``core/linking.py``). ``--crate-dir DIR`` says where this
crate's relative ``contentUrl`` values resolve. The same pass runs standalone
over a crate already on disk with
``fairscape_conversion link <crate> --link-crate DIR [-o OUT]``.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

#: Plugins whose ``import`` source is a path, not a parsed document.
PATH_SOURCE_IMPORTS = ("c2m2", "cpm", "redcap", "frictionless", "galaxy")


def _read(path: Path):
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)


def _write(path: Path, data):
    if path.suffix in (".yaml", ".yml"):
        import yaml
        path.write_text(yaml.dump(data, sort_keys=False, allow_unicode=True))
    elif isinstance(data, str):
        path.write_text(data)
    else:
        path.write_text(json.dumps(data, indent=2, default=str))


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    argv = list(argv)
    provn = "--provn" in argv
    argv = [a for a in argv if a != "--provn"]
    options = {}
    linked = []
    while "--link-crate" in argv:                # linked crates, repeatable
        i = argv.index("--link-crate")
        linked.append(argv[i + 1])
        del argv[i:i + 2]
    if "--crate-dir" in argv:
        i = argv.index("--crate-dir")
        options["crate_dir"] = argv[i + 1]
        del argv[i:i + 2]
    if "--records" in argv:                      # redcap: the record export CSV
        i = argv.index("--records")
        options["records"] = argv[i + 1]
        del argv[i:i + 2]
    if argv and argv[0] == "link":
        return _link_command(argv[1:], linked)
    if len(argv) < 4 or argv[0] != "convert":
        print(__doc__)
        return 1
    if linked:
        options["linked_crates"] = linked
        options["link_report"] = True
        if direction_of(argv) == "import" and "crate_dir" not in options:
            options["crate_dir"] = _guess_crate_dir(argv)
    _, plugin_name, direction, in_path, *rest = argv
    if direction not in ("import", "export"):
        print(f"direction must be import|export, got {direction!r}")
        return 1
    plugin = importlib.import_module(f"fairscape_conversion.plugins.{plugin_name}")

    if direction == "export" and plugin_name == "cpm" and provn:
        options["serialization"] = "provn"

    source = (in_path if direction == "import" and plugin_name in PATH_SOURCE_IMPORTS
              else _read(Path(in_path)))

    result = plugin.convert(direction, source, **options)
    if isinstance(result, dict) and "_linking" in result:
        matches = result.pop("_linking")
        print(f"linked crates: {len(matches)} input(s) resolved", file=sys.stderr)
        for m in matches:
            print(f"  {m['old_id']} -> {m['new_id']}  [{m['method']}]", file=sys.stderr)
    if rest:
        _write(Path(rest[0]), result)
        print(f"wrote {rest[0]}")
    elif isinstance(result, str):
        print(result)
    else:
        print(json.dumps(result, indent=2, default=str))
    return 0


def direction_of(argv):
    return argv[2] if len(argv) > 2 else None


def _guess_crate_dir(argv):
    """With ``--link-crate`` and no ``--crate-dir``, relative locators in the
    new crate are taken to be relative to where it is being written (the
    output file's folder), else to the input's folder."""
    rest = argv[4:]
    anchor = Path(rest[0]) if rest else Path(argv[3])
    return str(anchor.resolve().parent)


def _link_command(argv, linked):
    """``link <crate> [--link-crate DIR ...] [-o OUT]`` — the pass by itself."""
    from .linking import link_crate_file
    output = None
    if "-o" in argv:
        i = argv.index("-o")
        output = argv[i + 1]
        del argv[i:i + 2]
    if len(argv) != 1 or not linked:
        print("usage: fairscape_conversion link <crate-dir|ro-crate-metadata.json> "
              "--link-crate DIR [--link-crate DIR ...] [-o OUT]")
        return 1
    report = link_crate_file(argv[0], linked, output=output)
    print(report.summary(), file=sys.stderr)
    for m in report.matches:
        print(f"  {m.old_id} -> {m.new_id}  [{m.method}]", file=sys.stderr)
    print(f"wrote {output or argv[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
