"""Linked crates — a converted crate reuses an upstream crate's identity for
anything it only *consumed*.

Two independent runs do not know about each other: a Nextflow crate says it
generated ``labels.tsv``; an MLflow crate converted later says it used a file
called ``labels.tsv`` and mints a fresh, producer-less Dataset for it. Nothing
ties the two together. This module is the tie.

Given the crate a conversion just produced and one or more *linked crates*
already on disk, ``link_crate`` looks at every producer-less entity in the new
crate, works out where its bytes are, and asks each linked crate whether it
already describes that file. On a hit the new crate's node is replaced by a
**stub** of the upstream entity:

* the stub carries the upstream ``@id`` (the exact ARK, never re-minted), the
  upstream's descriptive fields, the file's absolute ``localPath``;
* it carries ``isPartOf`` -> the upstream crate's root, and that root appears
  in the graph once as a crate stub whose ``ro-crate-metadata`` field points
  at the upstream ``ro-crate-metadata.json`` (the same field a release crate
  uses for its constituents, so ``fairscape-artifacts`` can load it);
* it carries **no** ``generatedBy`` and no copy of the upstream Computation —
  the producer lives in the upstream crate, and a tool that wants the chain
  follows the pointer.

Every reference to the old id in the graph (``usedDataset``, ``hasPart``,
``EVI:inputs`` …) is rewritten to the upstream id.

Matching is by evidence, in this order, because every tool hashes a different
source string into its ARKs and none of them can re-mint another's:

1. **path** — the same absolute file (``contentUrl`` resolved against each
   crate's directory, or ``localPath``);
2. **md5** — both sides declare a checksum and they agree;
3. **directory** — the file sits inside a directory the upstream crate
   describes as one Dataset (a Nextflow ``publishDir`` without
   ``expandDirectories``). The node keeps its own id and gains ``isPartOf``
   -> a stub of that directory Dataset.

Nothing here is plugin-specific: it reads the finished crate, so any importer
that puts a resolvable ``contentUrl``/``localPath`` on its nodes takes part.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

METADATA_FILENAME = "ro-crate-metadata.json"
SUBCRATE_PATH_FIELD = "ro-crate-metadata"
EVI = "https://w3id.org/EVI#"

REMOTE_SCHEMES = ("http://", "https://", "s3://", "gs://", "ftp://", "git://",
                  "ssh://", "wasbs://", "dbfs://", "az://", "abfs://")

#: Entity kinds a consumer can have taken from somewhere else.
_LINKABLE = ("Dataset", "Software", "MLModel")

#: Fields that state provenance or containment — never copied into a stub.
_EDGE_FIELDS = {
    "generatedBy", "prov:wasGeneratedBy", "wasGeneratedBy",
    "generated", "usedDataset", "usedSoftware", "usedMLModel", "usedSample",
    "usedInstrument", "derivedFrom", "prov:wasDerivedFrom", "wasDerivedFrom",
    "datasetUsedBy", "softwareUsedBy", "usedBy", "usedByComputation",
    "hasPart", "isPartOf", "evi:Schema", "schema", "hasSchema",
    "prov:used", "used", "prov:specializationOf", "specializationOf",
    "contentUrl", "localPath", "@id", SUBCRATE_PATH_FIELD,
    "https://w3id.org/EVI#inputs", "https://w3id.org/EVI#outputs",
    "EVI:inputs", "EVI:outputs", "inputs", "outputs",
}

#: Fields whose value names something in the upstream crate that this crate
#: does not carry; the consumer's own value is kept instead.
_CONSUMER_ONLY = {"evi:Schema", "schema", "hasSchema"}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _short_types(node: Dict[str, Any]) -> List[str]:
    raw = node.get("@type") or []
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for t in raw:
        t = str(t)
        for sep in ("#", "/", ":"):
            if sep in t:
                t = t.rsplit(sep, 1)[-1]
        out.append(t)
    return out


def _has_type(node: Dict[str, Any], *names: str) -> bool:
    types = _short_types(node)
    return any(n in types for n in names)


def _ref_ids(value) -> List[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and item.get("@id"):
            out.append(item["@id"])
    return out


def _generated_by(node: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    for f in ("generatedBy", "prov:wasGeneratedBy", "wasGeneratedBy",
              "derivedFrom", "prov:wasDerivedFrom", "wasDerivedFrom"):
        ids += _ref_ids(node.get(f))
    return ids


def _strip_file_scheme(value: str) -> Optional[str]:
    """``file:///x`` / ``file://x`` -> ``/x``; a remote URL -> None."""
    if value.startswith("file://"):
        value = value[len("file://"):]
    if value.startswith(REMOTE_SCHEMES) or "://" in value:
        return None
    return value or None


def _candidates(node: Dict[str, Any], base_dirs: Iterable[str]) -> List[str]:
    """Every absolute path a node's locators could mean, most specific first.

    A relative ``contentUrl`` is relative to the crate directory (first base);
    a relative ``localPath`` may be relative to the crate directory or the
    run directory that contains it, so every base is tried.
    """
    bases = [b for b in base_dirs if b]
    found: List[str] = []
    for f in ("contentUrl", "localPath"):
        raw = node.get(f)
        if not isinstance(raw, str) or not raw:
            continue
        p = _strip_file_scheme(raw)
        if not p:
            continue
        if os.path.isabs(p):
            found.append(os.path.normpath(p))
            continue
        for b in bases:
            found.append(os.path.normpath(os.path.join(b, p)))
    seen, out = set(), []
    for p in found:
        key = _canon(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _canon(path: str) -> str:
    """Comparison key: resolved symlinks when the path exists, else normpath."""
    try:
        return os.path.realpath(path)
    except OSError:
        return os.path.normpath(path)


def _find_root(graph: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_id = {n.get("@id"): n for n in graph if isinstance(n, dict)}
    desc = by_id.get(METADATA_FILENAME)
    if desc:
        about = _ref_ids(desc.get("about"))
        if about and about[0] in by_id:
            return by_id[about[0]]
    for n in graph:
        if n.get("@id") != METADATA_FILENAME and _has_type(n, "ROCrate"):
            return n
    return by_id.get("./") or (graph[0] if graph else {})


# ---------------------------------------------------------------------------
# the upstream side
# ---------------------------------------------------------------------------

@dataclass
class LinkedCrate:
    """An upstream crate loaded from disk, indexed for matching."""
    metadata_path: str                       # absolute path to its ro-crate-metadata.json
    root: Dict[str, Any]
    index: Dict[str, Dict[str, Any]]
    by_path: Dict[str, str] = field(default_factory=dict)   # canon path -> @id
    by_md5: Dict[str, str] = field(default_factory=dict)    # md5 -> @id
    dirs: Dict[str, str] = field(default_factory=dict)      # canon dir path -> @id
    paths: Dict[str, str] = field(default_factory=dict)     # @id -> the path we resolved

    @property
    def dir(self) -> str:
        return os.path.dirname(self.metadata_path)

    @property
    def root_id(self) -> str:
        return self.root.get("@id", "")

    @classmethod
    def load(cls, path: str) -> "LinkedCrate":
        import json
        given = str(path)
        path = os.path.abspath(os.path.expanduser(given))
        if os.path.isdir(path):
            path = os.path.join(path, METADATA_FILENAME)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"no {METADATA_FILENAME} to link to in {given}")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        graph = [n for n in data.get("@graph", []) if isinstance(n, dict)]
        crate = cls(metadata_path=path, root=_find_root(graph),
                    index={n["@id"]: n for n in graph if n.get("@id")})
        crate._index_paths()
        return crate

    def _index_paths(self) -> None:
        bases = [self.dir, os.path.dirname(self.dir)]
        for node_id, node in self.index.items():
            if node_id in (METADATA_FILENAME, self.root_id):
                continue
            if not _has_type(node, *_LINKABLE):
                continue
            md5 = node.get("md5")
            if isinstance(md5, str) and md5:
                self.by_md5.setdefault(md5.lower(), node_id)
            for p in _candidates(node, bases):
                key = _canon(p)
                if os.path.isdir(p):
                    self.dirs.setdefault(key, node_id)
                    self.paths.setdefault(node_id, p)
                    break
                # a path that exists wins outright; one that does not is still
                # a claim worth matching against (the crate may have moved)
                if key not in self.by_path or os.path.exists(p):
                    self.by_path[key] = node_id
                    self.paths[node_id] = p
                if os.path.exists(p):
                    break

    def match_path(self, path: str) -> Optional[str]:
        return self.by_path.get(_canon(path))

    def match_md5(self, md5: Optional[str]) -> Optional[str]:
        if not isinstance(md5, str) or not md5:
            return None
        return self.by_md5.get(md5.lower())

    def match_directory(self, path: str) -> Optional[str]:
        """The upstream directory Dataset that contains `path`, if any."""
        cur = os.path.dirname(_canon(path))
        while cur and cur != os.path.dirname(cur):
            if cur in self.dirs:
                return self.dirs[cur]
            cur = os.path.dirname(cur)
        return None


def load_linked_crates(specs) -> List[LinkedCrate]:
    """Accept paths (dirs or metadata files), LinkedCrate objects, or a mix."""
    if specs is None:
        return []
    if isinstance(specs, (str, os.PathLike, LinkedCrate)):
        specs = [specs]
    out: List[LinkedCrate] = []
    for s in specs:
        out.append(s if isinstance(s, LinkedCrate) else LinkedCrate.load(s))
    return out


# ---------------------------------------------------------------------------
# the consumer side
# ---------------------------------------------------------------------------

@dataclass
class Match:
    old_id: str
    new_id: str
    method: str                 # path | md5 | directory | id
    crate: LinkedCrate
    path: Optional[str] = None  # the consumer's resolved path, when known

    def as_dict(self) -> Dict[str, Any]:
        return {"old_id": self.old_id, "new_id": self.new_id, "method": self.method,
                "crate": self.crate.root_id, "crate_path": self.crate.metadata_path,
                "path": self.path}


@dataclass
class LinkReport:
    matches: List[Match] = field(default_factory=list)
    unmatched: List[str] = field(default_factory=list)   # producer-less ids left alone

    @property
    def linked_crates(self) -> List[LinkedCrate]:
        seen, out = set(), []
        for m in self.matches:
            if m.crate.metadata_path not in seen:
                seen.add(m.crate.metadata_path)
                out.append(m.crate)
        return out

    def summary(self) -> str:
        if not self.matches:
            return "linked crates: no inputs matched"
        by_method: Dict[str, int] = {}
        for m in self.matches:
            by_method[m.method] = by_method.get(m.method, 0) + 1
        parts = ", ".join(f"{n} by {k}" for k, n in sorted(by_method.items()))
        crates = ", ".join(c.root.get("name") or c.root_id for c in self.linked_crates)
        return (f"linked crates: {len(self.matches)} input(s) resolved ({parts}) "
                f"to {crates}; {len(self.unmatched)} left unlinked")


def _stub_of(upstream: Dict[str, Any], consumer: Dict[str, Any],
             crate: LinkedCrate, path: Optional[str]) -> Dict[str, Any]:
    """The node the consumer crate carries for an entity another crate owns."""
    stub: Dict[str, Any] = {"@id": upstream["@id"], "@type": upstream.get("@type")}
    for key, value in upstream.items():
        if key in _EDGE_FIELDS or key.startswith("@"):
            continue
        if value in (None, "", [], {}):
            continue
        stub[key] = value
    for key, value in consumer.items():
        if key.startswith("@") or key in stub:
            continue
        if key in _EDGE_FIELDS and key not in _CONSUMER_ONLY:
            continue
        if value in (None, "", [], {}):
            continue
        stub[key] = value
    local = path or crate.paths.get(upstream["@id"])
    if local:
        stub["localPath"] = os.path.abspath(local)
    remote = upstream.get("contentUrl")
    if isinstance(remote, str) and remote.startswith(REMOTE_SCHEMES):
        stub["contentUrl"] = remote            # a URL is location, not layout
    stub["isPartOf"] = [{"@id": crate.root_id}]
    return stub


def pointer_path(metadata_path: str, crate_dir: Optional[str]) -> str:
    """How one crate should write the path of another: relative when the two
    sit near each other (so the pair survives being moved or zipped together),
    absolute when they do not. A relative pointer that climbs to the
    filesystem root is noise, not portability, so three levels up is the
    limit.
    """
    metadata_path = os.path.abspath(metadata_path)
    if not crate_dir:
        return metadata_path
    try:
        rel = os.path.relpath(metadata_path, os.path.abspath(os.path.expanduser(str(crate_dir))))
    except ValueError:                  # different drive on Windows
        return metadata_path
    if rel.count(".." + os.sep) > 3:
        return metadata_path
    return rel.replace(os.sep, "/")


def _crate_stub(crate: LinkedCrate, crate_dir: Optional[str],
                parts: Iterable[str] = ()) -> Dict[str, Any]:
    """One node standing for the upstream crate, pointing at its metadata file.

    ``hasPart`` lists only the upstream entities this crate carries stubs
    of — true (they are part of it), resolvable here, and enough for
    ``fairscape_models``, which requires the field on every RO-Crate node.
    """
    pointer = pointer_path(crate.metadata_path, crate_dir)
    stub: Dict[str, Any] = {
        "@id": crate.root_id,
        "@type": crate.root.get("@type") or ["Dataset", EVI + "ROCrate"],
    }
    for key in ("name", "description", "version", "datePublished", "author",
                "license", "identifier", "keywords"):
        if crate.root.get(key) not in (None, "", [], {}):
            stub[key] = crate.root[key]
    stub["hasPart"] = [{"@id": i} for i in parts]
    stub[SUBCRATE_PATH_FIELD] = pointer
    stub["localPath"] = crate.metadata_path
    return stub


def _rewrite_refs(value, mapping: Dict[str, str]):
    """Replace every reference to an old id, at any depth."""
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        out, seen = [], set()
        for item in value:
            new = _rewrite_refs(item, mapping)
            key = new["@id"] if isinstance(new, dict) and set(new) == {"@id"} else (
                new if isinstance(new, str) else None)
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            out.append(new)
        return out
    if isinstance(value, dict):
        return {k: _rewrite_refs(v, mapping) for k, v in value.items()}
    return value


def link_crate(crate: Dict[str, Any], linked, *, crate_dir: Optional[str] = None,
               search_dirs: Iterable[str] = (), only_inputs: bool = True) -> LinkReport:
    """Rewrite `crate` in place so its consumed entities reuse upstream ids.

    ``linked`` is anything ``load_linked_crates`` accepts. ``crate_dir`` is
    where this crate's relative ``contentUrl`` values resolve and where the
    relative ``ro-crate-metadata`` pointer is computed from; without it only
    absolute locators can match and the pointer is absolute.

    ``search_dirs`` are further folders a *relative* locator may be counted
    from, tried after ``crate_dir``. Some importers record a path relative to
    where the run happened rather than to the crate — the Snakemake reporter
    writes ``../../other-run/results/x.tsv`` — and that folder is the caller's
    to know. Only ``crate_dir`` decides where the pointer is written from. A
    wrong base is harmless: the path it produces is simply not in any linked
    crate's index, so it matches nothing.

    ``only_inputs`` restricts matching to producer-less entities, which is
    what "consumed" means; pass False to also let this crate's own outputs
    be claimed by an upstream crate (rarely what you want).
    """
    crates = load_linked_crates(linked)
    report = LinkReport()
    if not crates:
        return report

    graph: List[Dict[str, Any]] = [n for n in crate.get("@graph", []) if isinstance(n, dict)]
    root = _find_root(graph)
    root_id = root.get("@id")
    base_dirs = [os.path.abspath(crate_dir)] if crate_dir else []
    for extra in search_dirs:
        extra = os.path.abspath(os.path.expanduser(str(extra)))
        if extra not in base_dirs:
            base_dirs.append(extra)
    linked_root_ids = {c.root_id for c in crates}

    mapping: Dict[str, str] = {}          # old consumer id -> upstream id
    replacements: Dict[str, Dict[str, Any]] = {}   # old id -> stub node
    claimed: set = set()                  # upstream ids already given a stub
    extra_nodes: Dict[str, Dict[str, Any]] = {}    # upstream ids to add (dirs, crate stubs)
    used_crates: Dict[str, LinkedCrate] = {}

    for node in graph:
        node_id = node.get("@id")
        if not node_id or node_id in (METADATA_FILENAME, root_id) or node_id in linked_root_ids:
            continue
        if not _has_type(node, *_LINKABLE) or _has_type(node, "ROCrate"):
            continue
        if only_inputs and _generated_by(node):
            continue

        paths = _candidates(node, base_dirs)
        hit: Optional[Tuple[LinkedCrate, str, str, Optional[str]]] = None

        if not _has_type(node, "Software"):
            # A node that already carries the upstream id (a run-time helper
            # logged the ARK itself). Software is excluded: two crates that
            # both describe the same engine mint the same deterministic ARK
            # without one having taken it from the other.
            for lc in crates:
                if node_id in lc.index:
                    hit = (lc, node_id, "id", paths[0] if paths else None)
                    break
        if hit is None:
            for p in paths:
                for lc in crates:
                    up = lc.match_path(p)
                    if up:
                        hit = (lc, up, "path", p)
                        break
                if hit:
                    break
        if hit is None:
            for lc in crates:
                up = lc.match_md5(node.get("md5"))
                if up:
                    hit = (lc, up, "md5", paths[0] if paths else None)
                    break
        if hit is None:
            for p in paths:
                for lc in crates:
                    up = lc.match_directory(p)
                    if up:
                        hit = (lc, up, "directory", p)
                        break
                if hit:
                    break

        if hit is None:
            report.unmatched.append(node_id)
            continue

        lc, up_id, method, path = hit
        used_crates[lc.metadata_path] = lc
        upstream = lc.index[up_id]

        if method == "directory":
            # keep our own node; say which upstream directory it sits in
            parts = _ref_ids(node.get("isPartOf"))
            if up_id not in parts:
                node["isPartOf"] = [{"@id": i} for i in parts] + [{"@id": up_id}]
            if up_id not in extra_nodes:
                extra_nodes[up_id] = _stub_of(upstream, {}, lc, lc.paths.get(up_id))
            report.matches.append(Match(node_id, up_id, method, lc, path))
            continue

        if up_id in claimed:
            # a second consumer node for the same upstream entity: fold it in
            mapping[node_id] = up_id
            report.matches.append(Match(node_id, up_id, method, lc, path))
            continue
        claimed.add(up_id)
        replacements[node_id] = _stub_of(upstream, node, lc, path)
        if node_id != up_id:
            mapping[node_id] = up_id
        report.matches.append(Match(node_id, up_id, method, lc, path))

    if not report.matches:
        return report

    for lc in used_crates.values():
        parts = [m.new_id for m in report.matches
                 if m.crate is lc and m.new_id not in extra_nodes.get(lc.root_id, {})]
        seen_parts: List[str] = []
        for pid in parts:
            if pid not in seen_parts:
                seen_parts.append(pid)
        extra_nodes.setdefault(lc.root_id, _crate_stub(lc, crate_dir, seen_parts))

    # rebuild the graph: swap stubs in, drop folded duplicates, rewrite refs
    new_graph: List[Dict[str, Any]] = []
    emitted = set()
    for node in graph:
        node_id = node.get("@id")
        if node_id in replacements:
            node = replacements[node_id]
        elif node_id in mapping:                 # folded into an earlier stub
            continue
        node = _rewrite_refs(node, mapping) if mapping else node
        if node.get("@id") in emitted:
            continue
        emitted.add(node.get("@id"))
        new_graph.append(node)
    for node_id, node in extra_nodes.items():
        if node_id not in emitted:
            emitted.add(node_id)
            new_graph.append(node)

    crate["@graph"] = new_graph
    return report


def link_crate_file(path: str, linked, *, output: Optional[str] = None,
                    search_dirs: Iterable[str] = (),
                    only_inputs: bool = True) -> LinkReport:
    """``link_crate`` for a crate on disk; writes back in place unless `output`."""
    import json
    path = os.path.abspath(os.path.expanduser(str(path)))
    if os.path.isdir(path):
        path = os.path.join(path, METADATA_FILENAME)
    with open(path, encoding="utf-8") as fh:
        crate = json.load(fh)
    report = link_crate(crate, linked, crate_dir=os.path.dirname(path),
                        search_dirs=search_dirs, only_inputs=only_inputs)
    target = os.path.abspath(output) if output else path
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(crate, fh, indent=2, default=str)
    return report
