#!/usr/bin/env python3
"""Use case: someone else's Cromwell runs — real pipelines, on the cloud.

Three metadata files as Cromwell wrote them, taken from public GitHub
repositories (see ``public-runs/README.md`` for where each came from):

* ``encode-atac-seq``  — the ENCODE ATAC-seq pipeline on Google Cloud via
  Caper, 12 calls (scatter shards, peak calling, IDR, QC), 97 gs:// files;
* ``encode-mirna-seq`` — the ENCODE miRNA-seq pipeline on Google Cloud,
  cutadapt -> STAR -> wigToBigWig, two replicates in a scatter;
* ``broad-subworkflow-hello`` — Cromwell's own test of a subworkflow call.

None of the files are here, so ``crate_dir`` is a scratch directory and every
dataset is a remote ``contentUrl``. Then the part that matters: does the
provenance graph say what the *pipeline* says? The WDL each run submitted is
inside its metadata (``submittedFiles.workflow``), so this reads the call
graph out of it — which call's outputs each call consumes, following the
workflow-level declarations WDL routes values through — and checks that
every computation -> computation edge in the crate is one the WDL declares.

    python examples/import_cromwell_public.py
"""

import re
import tempfile
from pathlib import Path

import _example as ex

RUNS = Path(__file__).resolve().parent / "public-runs" / "cromwell"

WDL_TYPE = r"(?:Array\[[^\]]*\]|Map\[[^\]]*\]|Pair\[[^\]]*\]|File|String|Int|Float|Boolean|Object)\??\+?"


def _block(text, start):
    """Text of the {...} block opening at ``start`` (index of the brace)."""
    depth, i = 0, start
    while i < len(text):
        depth += text[i] == "{"
        depth -= text[i] == "}"
        i += 1
        if depth == 0:
            return text[start + 1:i - 1]
    return text[start + 1:]


def wdl_call_graph(wdl):
    """alias -> the call aliases whose outputs it consumes.

    A call consumes another's outputs either directly (``peak = call_peak.bfilt``)
    or through a workflow-level declaration (``File? blacklist_ = ... read_genome_tsv.blacklist``
    then ``blacklist = blacklist_``), so declarations are resolved transitively.
    Good enough for the WDL 1.0 the ENCODE pipelines are written in; not a parser.
    """
    wf = _block(wdl, re.search(r"^\s*workflow\s+\w+\s*(\{)", wdl, re.M).start(1))
    calls = {}
    for m in re.finditer(r"\bcall\s+([\w.]+)(?:\s+as\s+(\w+))?\s*(\{)?", wf):
        alias = m.group(2) or m.group(1).split(".")[-1]
        calls[alias] = _block(wf, m.start(3)) if m.group(3) else ""
    decls = {}
    starts = [(m.start(), m.group(1), m.end())
              for m in re.finditer(r"^[ \t]*" + WDL_TYPE + r"[ \t]+(\w+)[ \t]*=", wf, re.M)]
    bounds = [m.start() for m in re.finditer(
        r"^[ \t]*(?:" + WDL_TYPE + r"[ \t]+\w+[ \t]*=|call\b|if\b|scatter\b|\}|output\b|input\b)", wf, re.M)]
    for start, name, end in starts:
        decls[name] = wf[end:min([b for b in bounds if b > start], default=len(wf))]

    def refs(expr, seen=()):
        out = {r for r in re.findall(r"\b(\w+)(?=\.\w+)", expr) if r in calls}
        for r in set(re.findall(r"\b(\w+)\b", expr)):
            if r in decls and r not in seen:
                out |= refs(decls[r], seen + (r,))
        return out

    return {alias: refs(body) - {alias} for alias, body in calls.items()}


def call_name(computation_name):
    return computation_name.split(" (")[0]          # 'call_peak (shard=1)' -> 'call_peak'


EXPLAINED = {
    # qc_report takes the genome *name* from read_genome_tsv, a String, not a file
    ("read_genome_tsv", "qc_report"): "a String (the genome name), not a file",
}

ex.banner("Public Cromwell runs -> EVI RO-Crates, checked against their WDL",
          have="metadata.json files other people's Cromwell runs wrote",
          want="a crate per run whose computation graph is the WDL's call graph")

all_ok = True
for metadata in sorted(RUNS.glob("*.metadata.json")):
    run = ex.read(metadata)
    calls = sum(len(v) for v in run["calls"].values())
    print(f"\n--- {metadata.name}: '{run['workflowName']}' {run['status']}, "
          f"{calls} top-level call(s), Cromwell "
          f"{next((e.get('cromwellVersion') for e in run.get('workflowProcessingEvents', [])), '?')}")

    crate = ex.plugin("cromwell").convert("import", str(metadata),
                                          crate_dir=tempfile.mkdtemp(prefix="public-run-"))
    ex.summarize(crate, limit=8)
    ex.show_provenance(crate, limit=10)
    ex.write(crate, ex.OUT / "cromwell-public" / metadata.name.replace(".metadata.json", "") / "ro-crate-metadata.json")

    ran = {call_name(n["name"]) for n in crate["@graph"]
           if "Computation" in str(n.get("@type")) and n.get("isPartOf")}
    graph = wdl_call_graph(run["submittedFiles"]["workflow"]) if run.get("submittedFiles", {}).get("workflow") else {}
    expected = {(a, b) for b, srcs in graph.items() if b in ran for a in srcs if a in ran}
    actual = {(call_name(a), call_name(b)) for a, b in ex.computation_edges(crate)}
    all_ok &= ex.check_pipeline(actual, expected, "WDL call graph", EXPLAINED)

print(f"\n{'all runs match' if all_ok else 'SOME RUNS DIFFER FROM'} their WDL")
