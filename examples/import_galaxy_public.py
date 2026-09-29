#!/usr/bin/env python3
"""Use case: someone else's Galaxy runs — real invocation exports from usegalaxy.eu.

Two ``.rocrate.zip`` files exactly as Galaxy's *export invocation* wrote them,
published on Zenodo by their authors (see ``public-runs/README.md``): X-ray
absorption spectroscopy analyses with the Larch tools, one a six-step
tutorial reproduction, one an eleven-step analysis whose Athena step writes a
collection that three ``__EXTRACT_DATASET__`` steps pull single files out of
for three Artemis fits.

Each zip holds both Galaxy's Workflow Run RO-Crate and Galaxy's own model
store; this reads the model store (every job, not just the invocation) — see
``import_galaxy.py``. Then the check: the ``.ga`` workflow definition in the
zip says which step feeds which; the crate's computation graph must agree.
One rule bridges them: a step that only *copies* a dataset out of a
collection (``__EXTRACT_DATASET__``) adds no file to the world, so the crate
keeps the file's real producer and the copy step is transparent — the
workflow's ``athena -> extract -> artemis`` is, in the crate, ``athena ->
extract`` (it did read the collection) plus ``athena -> artemis``.

    python examples/import_galaxy_public.py
"""

import json
import re
import zipfile
from pathlib import Path

import _example as ex

RUNS = Path(__file__).resolve().parent / "public-runs" / "galaxy"
COPY_TOOLS = ("__EXTRACT_DATASET__",)


def ga_step_graph(ga):
    """(source step, target step) for every tool-step connection in a .ga,
    with copy-only steps made transparent: they keep their inputs, and what
    they fed is fed by whatever fed them."""
    steps = {int(k): v for k, v in ga["steps"].items()}
    tool = {i: s for i, s in steps.items() if s.get("type") == "tool"}
    edges = set()
    for i, s in tool.items():
        for conns in (s.get("input_connections") or {}).values():
            for c in (conns if isinstance(conns, list) else [conns]):
                if c["id"] in tool:
                    edges.add((c["id"], i))
    for i, s in tool.items():
        if s.get("tool_id") in COPY_TOOLS:
            into = {a for a, b in edges if b == i}
            outof = {b for a, b in edges if a == i}
            # the copy step still consumes (its edges in stay); it produces
            # nothing, so its edges out become its producers' edges out
            edges = {(a, b) for a, b in edges if a != i} | {(a, b) for a in into for b in outof}
    return edges


def step_of(name):
    m = re.search(r"\(step (\d+)[:)]", name)
    return int(m.group(1)) if m else None


ex.banner("Public Galaxy runs -> EVI RO-Crates, checked against their .ga",
          have="invocation exports (.rocrate.zip) other people published",
          want="a crate per run whose job graph is the workflow's step graph")

all_ok = True
for archive in sorted(RUNS.glob("*.rocrate.zip")):
    with zipfile.ZipFile(archive) as z:
        ga = json.loads(z.read(next(n for n in z.namelist() if n.endswith(".ga"))))
        jobs = json.loads(z.read("jobs_attrs.txt"))
    print(f"\n--- {archive.name}: '{ga.get('name')}', {len(ga['steps'])} step(s), "
          f"{len(jobs)} job(s), Galaxy {max(j.get('galaxy_version') or '' for j in jobs) or '?'}")

    crate = ex.plugin("galaxy").convert("import", str(archive), author="Zenodo depositor")
    ex.summarize(crate, limit=8)
    ex.show_provenance(crate, limit=10)
    ex.write(crate, ex.OUT / "galaxy-public" / archive.name.replace(".rocrate.zip", "") / "ro-crate-metadata.json")

    comps = [n for n in crate["@graph"] if "Computation" in str(n.get("@type"))]
    outside = [c["name"] for c in comps if c["name"].endswith("(outside the invocation)")]
    print(f"\n{len(comps)} computation(s): the invocation, "
          f"{sum(1 for c in comps if c['name'].startswith('upload'))} upload(s), "
          f"{sum(1 for c in comps if step_of(c['name']) is not None)} step job(s)"
          + (f", {len(outside)} outside the invocation" if outside else ""))

    actual = {(step_of(a), step_of(b)) for a, b in ex.computation_edges(crate)
              if step_of(a) is not None and step_of(b) is not None}
    all_ok &= ex.check_pipeline(actual, ga_step_graph(ga), ".ga step graph")

print(f"\n{'all runs match' if all_ok else 'SOME RUNS DIFFER FROM'} their workflow")
