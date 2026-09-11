#!/usr/bin/env python3
"""Shared plumbing for the runnable examples in this folder.

Two jobs, both boring on purpose so each example script stays about its
format and not about setup:

1. make ``import fairscape_conversion`` resolve to *this* checkout, so the
   examples run from a fresh clone with nothing installed (same
   ``spec_from_file_location`` trick as ``tests/conftest.py``);
2. print a conversion the same way every time — node counts by type, the
   provenance edges, and a golden check where the conversion is deterministic.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]     # the fairscape_conversion package
PLUGINS = ROOT / "plugins"
OUT = Path(__file__).resolve().parent / "out"  # gitignored scratch space


def load_package():
    """Bind ``fairscape_conversion`` to this directory and return the module."""
    if "fairscape_conversion" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "fairscape_conversion", ROOT / "__init__.py",
            submodule_search_locations=[str(ROOT)])
        module = importlib.util.module_from_spec(spec)
        sys.modules["fairscape_conversion"] = module
        spec.loader.exec_module(module)
    return sys.modules["fairscape_conversion"]


def plugin(name):
    """``plugin("d4d").convert("import", ...)`` — import a plugin by name."""
    load_package()
    return importlib.import_module(f"fairscape_conversion.plugins.{name}")


# ---------------------------------------------------------------- reading


def read(path):
    """Read a fixture by extension (the CLI's ``_read``, reused here)."""
    path = Path(path)
    if path.suffix in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


def plain(obj):
    """Down to plain JSON types — how the goldens were serialized."""
    return json.loads(json.dumps(obj, default=str))


# ---------------------------------------------------------------- writing


def write(obj, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix in (".yaml", ".yml"):
        import yaml
        path.write_text(yaml.dump(obj, sort_keys=False, allow_unicode=True))
    else:
        path.write_text(json.dumps(obj, indent=2, default=str))
    rel = path.resolve()
    try:
        rel = rel.relative_to(Path.cwd())
    except ValueError:
        pass
    print(f"\nwrote {rel}")
    return path


# ---------------------------------------------------------------- printing


def banner(title, have, want):
    print("=" * 72)
    print(title)
    print(f"  you have : {have}")
    print(f"  you want : {want}")
    print("=" * 72)


def _short(type_value):
    """['Dataset', 'https://w3id.org/EVI#ROCrate'] -> 'Dataset, EVI#ROCrate'."""
    prefixes = {"https://w3id.org/EVI#": "EVI#", "evi:": "EVI#", "EVI:": "EVI#",
                "https://schema.org/": "", "http://www.w3.org/ns/prov#": "prov:"}
    values = type_value if isinstance(type_value, list) else [type_value]
    out = []
    for value in values:
        text = str(value)
        for prefix, replacement in prefixes.items():
            if text.startswith(prefix):
                text = replacement + text[len(prefix):]
                break
        out.append(text)
    return ", ".join(out)


def summarize(crate, limit=40):
    """Print the @graph as a type/name table — the quickest 'did that work?'."""
    graph = crate.get("@graph", [])
    print(f"\n{len(graph)} nodes in @graph")
    print(f"  {'@type':<34} name")
    print(f"  {'-' * 34} {'-' * 30}")
    for node in graph[:limit]:
        name = node.get("name") or node.get("@id", "")
        print(f"  {_short(node.get('@type', '')):<34} {str(name)[:60]}")
    if len(graph) > limit:
        print(f"  ... {len(graph) - limit} more")


PROV_EDGES = ("usedSoftware", "usedDataset", "generatedBy", "generated",
              "isPartOf", "evi:usedSoftware", "evi:usedDataset",
              "evi:generatedBy", "evi:generated")


def show_provenance(crate, limit=25):
    """Print the EVI edges — the part a table of names cannot show."""
    graph = crate.get("@graph", [])
    names = {n.get("@id"): (n.get("name") or n.get("@id")) for n in graph}

    def label(ref):
        guid = ref.get("@id") if isinstance(ref, dict) else ref
        return str(names.get(guid, guid))[:44]

    print("\nprovenance edges")
    shown = 0
    for node in graph:
        for key in PROV_EDGES:
            if key not in node:
                continue
            refs = node[key] if isinstance(node[key], list) else [node[key]]
            for ref in refs:
                if shown >= limit:
                    print("  ... (more edges in the written crate)")
                    return
                print(f"  {label({'@id': node.get('@id')}):<44} "
                      f"--{key.split(':')[-1]}--> {label(ref)}")
                shown += 1
    if not shown:
        print("  (none — this format carries no computation edges)")


def check_same_entities(result, crate_path, ignore_types=()):
    """Compare a conversion against a crate checked in beside its workflow.

    The examples that run on a real pipeline cannot use a golden file: the
    checked-in crate went through fairscape-cli afterwards, which adds the
    inverse EVI links (``generatedBy`` gets a ``generated`` on the other end,
    and so on) and so is a superset of what ``convert`` returns. What must
    still hold is that both describe exactly the same entities — same ARKs,
    same names — so that is what this checks.
    """
    want = {n["@id"]: n.get("name")
            for n in json.loads(Path(crate_path).read_text())["@graph"]
            if not any(t in str(n.get("@type")) for t in ignore_types)}
    got = {n["@id"]: n.get("name") for n in result["@graph"]}
    missing, extra = set(want) - set(got), set(got) - set(want)
    ok = not missing and not extra
    rel = Path(crate_path).parent.name + "/" + Path(crate_path).name
    print(f"\n{'MATCHES' if ok else 'DIFFERS FROM'} the entities in {rel} "
          f"({len(got)} node(s))")
    for guid in sorted(missing):
        print(f"  only in the crate: {guid} ({want[guid]})")
    for guid in sorted(extra):
        print(f"  only in this conversion: {guid} ({got[guid]})")
    return ok


def check_golden(result, plugin_name):
    """Compare against the plugin's reviewed golden.json — the examples that
    are deterministic say so out loud, so a drift shows up when you run one."""
    golden = json.loads((PLUGINS / plugin_name / "golden.json").read_text())
    ok = plain(result) == golden
    print(f"\n{'MATCHES' if ok else 'DIFFERS FROM'} "
          f"plugins/{plugin_name}/golden.json")
    return ok
