#!/usr/bin/env python3
"""Tiny CLI: ``fairscape_conversion convert <plugin> <import|export> <input> [output]``.

Reads JSON or YAML by extension, dispatches to the named plugin's ``convert``,
writes JSON (or YAML for a ``.yaml``/``.yml`` output path). The library API
(``fairscape_conversion.plugins.<name>.convert``) is what the tests and other code call; this
is only a convenience wrapper.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


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
    else:
        path.write_text(json.dumps(data, indent=2, default=str))


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 4 or argv[0] != "convert":
        print(__doc__)
        return 1
    _, plugin_name, direction, in_path, *rest = argv
    if direction not in ("import", "export"):
        print(f"direction must be import|export, got {direction!r}")
        return 1
    plugin = importlib.import_module(f"fairscape_conversion.plugins.{plugin_name}")
    result = plugin.convert(direction, _read(Path(in_path)))
    if rest:
        _write(Path(rest[0]), result)
        print(f"wrote {rest[0]}")
    else:
        print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
