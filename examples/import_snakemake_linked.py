#!/usr/bin/env python3
"""Use case: a workflow's only input was another workflow's output, and both
already have crates. Link them after the fact, with no conversion at all.

``linked-crates/snakemake-count/`` is a one-rule Snakemake run that counted,
per chromosome, the variants ``snakemake-variant-calling/`` called. The
FAIRSCAPE reporter wrote its crate at the end of the run
(``run/reporter-crate.json``, checked in untouched). In it,
``variant_summary.tsv`` is a producer-less Dataset with a fresh ARK: the
reporter had no way to know the file was another crate's output.

This script copies that crate into place and runs the standalone linking
command on it:

    fairscape_conversion link linked-crates/snakemake-count \\
        --link-crate examples/snakemake-variant-calling

Afterwards the input carries the *variant-calling crate's* ARK for the table,
``isPartOf`` that crate, and the crate itself appears once as a pointer.
``fairscape-artifacts`` follows the pointer, so the evidence graph of the
one-rule run continues through bcftools_call, samtools_sort and bwa_map back
to the reads.

The same pass ran inside a conversion in ``import_mlflow_linked.py``; here it
runs over a crate a different tool wrote, which is the point: it reads the
finished crate and matches by file path, so any crate takes part.

    python examples/import_snakemake_linked.py
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import _example as ex

HERE = Path(__file__).resolve().parent
UPSTREAM = HERE / "snakemake-variant-calling"
CONSUMER = HERE / "linked-crates" / "snakemake-count"
CRATE = CONSUMER / "ro-crate-metadata.json"

ex.banner("Two Snakemake runs, two crates -> linked after the fact",
          have="the crate the FAIRSCAPE reporter wrote for a run whose only "
               "input was another run's output, and that other run's crate",
          want="the consumer's input to BE the upstream crate's entity")

ex.load_package()
shutil.copy(CONSUMER / "run" / "reporter-crate.json", CRATE)

before = json.loads(CRATE.read_text())
orphan = next(n for n in before["@graph"] if n.get("name") == "variant_summary.tsv")
print(f"\nas the reporter wrote it, the input is a fresh, producer-less Dataset:\n"
      f"  {orphan['@id']}   localPath={orphan.get('localPath')}")

# the CLI, exactly as you would type it (module form; `fairscape link` with the CLI installed)
cmd = [sys.executable, "-m", "fairscape_conversion.core.cli", "link", str(CONSUMER),
       "--link-crate", str(UPSTREAM)]
print("\n$ " + " ".join(p.replace(str(HERE.parent) + "/", "") for p in cmd))
result = subprocess.run(cmd, cwd=HERE.parent, capture_output=True, text=True, check=True)
print(result.stderr.rstrip())

crate = json.loads(CRATE.read_text())
nodes = {n["@id"]: n for n in crate["@graph"]}
upstream_root = json.loads((UPSTREAM / "ro-crate-metadata.json").read_text())
upstream_ids = {n["@id"] for n in upstream_root["@graph"]}
stub = next(n for n in crate["@graph"] if n.get("name") == "variant_summary.tsv")
assert stub["@id"] in upstream_ids and orphan["@id"] not in nodes
assert "generatedBy" not in stub
pointer = next(n for n in crate["@graph"] if n.get("ro-crate-metadata"))

ex.show_provenance(crate, limit=14)
print("\nthe stub:")
print(json.dumps({k: stub[k] for k in ("@id", "name", "description", "localPath", "isPartOf")
                  if k in stub}, indent=2))
print(f"\nthe pointer: {pointer['@id']}\n  ro-crate-metadata: {pointer['ro-crate-metadata']}")
print("\nSnakemake itself is described by both crates under the same ARK and is "
      "NOT claimed:\n  " + ", ".join(n["name"] for n in crate["@graph"]
                                     if "Software" in str(n.get("@type"))
                                     and n["@id"] in upstream_ids and not n.get("isPartOf")))

try:
    from fairscape_artifacts import evidence, cli as artifacts_cli
    from fairscape_artifacts.crate import Crate
except ImportError:
    print("\n(fairscape_artifacts not importable: skipping the evidence graph)")
    sys.exit(0)

graph = evidence.build(Crate.load(str(CONSUMER)))["@graph"]
upstream_steps = sorted({n["name"] for n in graph.values()
                         if n.get("crate") and "Computation" in str(n.get("@type"))})
print(f"\nevidence graph of the one-rule run: {len(graph)} nodes; the upstream "
      f"computations it now reaches:\n  " + ", ".join(upstream_steps))
reached = {step.split(" ")[0] for step in upstream_steps}
assert {"bcftools_call", "bwa_map", "samtools_sort", "variant_summary"} <= reached

artifacts_cli.main(["all", str(CONSUMER), "--no-review", "-q"])
print(f"\nwrote linked-crates/snakemake-count/ro-crate-evidence-graph.html and "
      f"ro-crate-datasheet.html")
