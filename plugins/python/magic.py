"""``%%fairscape track`` — record a Jupyter cell into a crate directory.

    %load_ext fairscape_conversion.plugins.python

    %%fairscape track --crate-dir ./my-crate --name normalize
    df = pd.read_csv("raw.csv")
    df.to_csv("normalized.csv")

Same options as the ``track`` command, minus the script. The cell's code is
saved as the run's Software under ``software/`` in the crate.
"""

from __future__ import annotations

import argparse
import shlex

from .record import IOCapture, _now
from .track import add_run


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="%%fairscape track", add_help=False)
    p.add_argument("command", choices=["track"])
    p.add_argument("--crate-dir", default=".")
    p.add_argument("--name")
    p.add_argument("--author")
    p.add_argument("--keyword", dest="keywords", action="append")
    p.add_argument("--input", dest="manual_inputs", action="append", default=[])
    p.add_argument("--link-crate", dest="link_crates", action="append", default=[])
    p.add_argument("--start-clean", action="store_true")
    return p


def fairscape(line, cell):
    try:
        args = _parser().parse_args(shlex.split(line))
    except SystemExit:
        print(_parser().format_usage())
        return

    from IPython import get_ipython
    ip = get_ipython()
    starttime = _now()
    with IOCapture() as capture:
        # IPython puts its own ``open`` in the user namespace, which calls
        # io.open directly and so bypasses the builtins patch.
        ns_open = ip.user_ns.get("open")
        if ns_open is not None:
            def tracked_open(file, mode="r", *args, **kwargs):
                capture.opened(file, mode)
                return ns_open(file, mode, *args, **kwargs)
            ip.user_ns["open"] = tracked_open
        try:
            result = ip.run_cell(cell)
        finally:
            if ns_open is not None:
                ip.user_ns["open"] = ns_open
    if not result.success:
        print("fairscape: the cell failed; nothing was recorded")
        return

    name = args.name or f"cell-{starttime[:19].replace(':', '').replace('-', '')}"
    computation = add_run(
        code=cell, name=name, capture=capture, crate_dir=args.crate_dir,
        starttime=starttime, endtime=_now(), author=args.author,
        keywords=args.keywords, manual_inputs=args.manual_inputs,
        link_crates=args.link_crates, clean=args.start_clean)
    if computation is None:
        print("fairscape: no file I/O detected; nothing was recorded")
    else:
        print(f"fairscape: {computation['@id']} "
              f"({len(computation.get('usedDataset', []))} in, "
              f"{len(computation.get('generated', []))} out)")


def load_ipython_extension(ipython):
    ipython.register_magic_function(fairscape, magic_kind="cell", magic_name="fairscape")
