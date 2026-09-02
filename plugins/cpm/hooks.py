#!/usr/bin/env python3
"""CPM <-> EVI: ``CpmPlugin`` orchestration.

Import (CPM RO-Crate -> EVI) reads the crate's ``CPMProvenanceFile`` entries,
parses each PROV bundle (PROV-N or PROV-JSON — see ``provn.py``), merges the
bundles' elements by qualified id, and runs them through the shared pipeline.
The cross-organization join costs nothing: CPM links bundles by giving the
sender's ``senderConnector`` and the receiver's ``receiverConnector`` the SAME
identifier, and ARKs are minted deterministically from that identifier — so
the chain stitches into one graph by construction.

Deliberate mapping choices (deviations from a naive PROV mapping):

* ``cpm:mainActivity`` and untyped domain activities -> EVI ``Computation``
  (domain activities get ``isPartOf`` their bundle's main activity).
* ``cpm:receiptActivity`` — the cross-org data transfer — is KEPT, as a plain
  ``prov:Activity`` node (not a Computation, not dropped): transfers are real
  provenance but not computations.
* connectors / externalInputs -> ``Dataset`` with their CPM role recorded in
  ``additionalType`` (string form, e.g. ``"cpm:senderConnector"``, exactly as
  the reference bundles themselves write it — CPM publishes no namespace URI).
* one bundle = one org's part: every imported node points at its bundle's
  registered ``CPMProvenanceFile`` Dataset via ``subjectOf`` (the file
  describes the element; ``isPartOf`` would claim containment).
* the meta-provenance bundle (bundle version history) is not imported; the
  ``CPMMetaProvenanceFile`` is registered as a plain Dataset.

Export (EVI -> CPM) is bespoke: nodes become PROV statements grouped back into
bundles (via the round-trip ``cpmBundleId`` / ``identifier`` markers when the
crate came from CPM; a single bundle otherwise), returned as PROV-JSON — one
of the four serializations the CPM RO-Crate profile allows — or PROV-N text
via ``serialization="provn"``.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from ...core import Context, PluginBase, Record, SourceRecord
from .parsers import DEFAULT_NAAN, IMPORT_PARSERS, mint_ark
from . import provn

CONTEXT_IMPORT = {
    "@vocab": "https://schema.org/",
    "evi": "https://w3id.org/EVI#",
    "prov": "http://www.w3.org/ns/prov#",
}

FAIRSCAPE_PROFILE = "https://w3id.org/fairscape/profile/0.1"

_CPM_FILE_TYPES = ("CPMProvenanceFile", "CPMMetaProvenanceFile")

# CPM prov:type string -> our entities.csv source_type for activities.
_ACTIVITY_SOURCE_TYPE = {"mainActivity": "mainActivity",
                         "receiptActivity": "transferActivity"}

_QN_RE = re.compile(r"^[A-Za-z_][\w.-]*:\S")


def _types_of(node) -> list:
    t = node.get("@type")
    if not t:
        return []
    return t if isinstance(t, list) else [t]


def _kind(node) -> str:
    types = _types_of(node)
    last = str(types[-1]) if types else ""
    return last.split("#")[-1].split("/")[-1].split(":")[-1]


def _ref_ids(value) -> list:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    out = []
    for v in values:
        if isinstance(v, dict) and v.get("@id"):
            out.append(v["@id"])
        elif isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out


def _append_ref(node: dict, key: str, target_id: str):
    ref = {"@id": target_id}
    refs = node.setdefault(key, [])
    if ref not in refs:
        refs.append(ref)


# ============================================================================
# Loading — crate + bundle files, from a path or a pre-assembled dict
# ============================================================================

def _parse_bundle_document(payload):
    """PROV-N text or a PROV-JSON dict -> provn.Document."""
    if isinstance(payload, dict):
        return provn.parse_provjson(payload)
    text = str(payload).lstrip()
    if text.startswith("{"):
        return provn.parse_provjson(json.loads(text))
    return provn.parse_provn(text)


def _load_source(source):
    """-> (crate dict, [(file_id, crate_node, provn.Document, is_meta), ...]).

    ``source`` is a crate directory / ``ro-crate-metadata.json`` path, or a
    dict ``{"crate": {...}, "bundles": {file_id: provn-text-or-provjson}}``.
    """
    if isinstance(source, dict) and "@graph" not in source:
        crate, payloads = source["crate"], dict(source.get("bundles") or {})
        read = lambda file_id: payloads[file_id]        # noqa: E731
        available = set(payloads)
    else:
        path = Path(source) if not isinstance(source, dict) else None
        if path is not None:
            base = path if path.is_dir() else path.parent
            crate_path = base / "ro-crate-metadata.json"
            crate = json.loads(crate_path.read_text())

            def read(file_id):
                # A crate may register its bundles under absolute URLs
                # (remote provenance); files fetched next to the metadata
                # are found by their basename.
                candidate = base / file_id
                if not candidate.is_file():
                    candidate = base / file_id.rstrip("/").rsplit("/", 1)[-1]
                return candidate.read_text()
            available = None
        else:
            raise ValueError(
                "cpm import needs a crate directory / ro-crate-metadata.json "
                "path, or a {'crate': ..., 'bundles': ...} dict")

    bundles = []
    for node in crate.get("@graph", []):
        types = _types_of(node)
        is_meta = "CPMMetaProvenanceFile" in types
        if not (is_meta or "CPMProvenanceFile" in types):
            continue
        file_id = node.get("@id", "")
        if available is not None and file_id not in available:
            continue
        try:
            doc = _parse_bundle_document(read(file_id))
        except (FileNotFoundError, OSError):
            continue                      # registered but not shipped (remote)
        bundles.append((file_id, node, doc, is_meta))
    if not bundles:
        raise ValueError("no readable CPMProvenanceFile entries in the crate")
    return crate, bundles


# ============================================================================
# The plugin
# ============================================================================

class CpmPlugin(PluginBase):
    """Common Provenance Model RO-Crate <-> FAIRSCAPE EVI RO-Crate."""

    name = "cpm"
    import_parsers = IMPORT_PARSERS

    def select_rules(self, ctx, rec):
        """Rules are keyed by the entities.csv source_type (element kinds share
        target types, so the default by-target selection would cross-apply)."""
        return ctx.mapping.import_rules_by_source(rec.rule.source_type)

    def pre(self, ctx: Context):
        naan = ctx.extras.get("naan", DEFAULT_NAAN)
        crate, bundle_files = _load_source(ctx.source)
        graph = crate.get("@graph", [])
        by_id = {n["@id"]: n for n in graph if n.get("@id")}
        descriptor = by_id.get("ro-crate-metadata.json", {})
        root = by_id.get(_ref_ids(descriptor.get("about"))[0] if descriptor.get("about") else "./", {})
        ctx.root = root
        ctx.by_id = by_id

        author = root.get("author") or root.get("creator") or root.get("publisher")
        author_ids = _ref_ids(author) if not isinstance(author, str) else []
        if author_ids:
            author = by_id.get(author_ids[0], {}).get("name") or author_ids[0]
        ctx.extras["root_meta"] = {
            "author": author if isinstance(author, str) else None,
            "datePublished": root.get("datePublished"),
            "keywords": [str(k) for k in (root.get("keywords") or [])] or None,
        }

        # ---- walk the bundles into one element table -----------------------
        elements: dict[str, dict] = {}      # qid -> element record data
        relations: list[tuple] = []         # (stmt name, args, bundle_id)
        parent_of: dict[str, str] = {}      # sub-activity qid -> mainActivity qid
        sender_agent: dict[str, str] = {}   # bundle_id -> senderAgent label
        prefixes: dict[str, str] = {}
        default_ns = ""
        file_records = []

        for file_id, node, doc, is_meta in bundle_files:
            bundle_ids = [b.ident for b in doc.bundles]
            file_records.append(SourceRecord(
                {**node, "qid": file_id, "label": node.get("name") or file_id,
                 "bundle_id": bundle_ids[0] if bundle_ids else "",
                 "is_meta": is_meta, "source_type": "cpmfile"},
                "cpmfile", file_id))
            if is_meta:
                continue                    # bundle version history: not imported
            prefixes.update(doc.prefixes)
            default_ns = default_ns or doc.default_ns
            for bundle in doc.bundles:
                prefixes.update(bundle.prefixes)
                for stmt in bundle.statements:
                    if stmt.name in ("entity", "activity", "agent"):
                        self._merge_element(elements, stmt, bundle.ident, file_id)
                    else:
                        relations.append((stmt.name, stmt.args, bundle.ident))

        # Referenced-but-undeclared ids (e.g. jump targets) become entity stubs.
        for _, args, bundle_id in relations:
            for qid in args:
                if qid and qid not in elements:
                    self._merge_element(
                        elements, provn.Statement("entity", [qid]), bundle_id, None)

        # dct:hasPart* on a main activity nominates its sub-activities.
        for qid, el in elements.items():
            if el["cpm_type"] == "mainActivity":
                for key, value in list(el["attrs"].items()):
                    if key.startswith("dct:hasPart"):
                        for sub in (value if isinstance(value, list) else [value]):
                            parent_of[str(sub)] = qid
                        del el["attrs"][key]
            if el["kind"] == "agent" and el["cpm_type"] == "senderAgent":
                sender_agent.setdefault(el["bundle_id"], el["label"] or el["local"])

        # ---- classify + mint ----------------------------------------------
        classified, guid_map = [], {}
        for sr in file_records:
            rule = self.classify(ctx, sr)
            classified.append((sr, rule))
            guid_map[sr.source_id] = mint_ark(
                naan, rule.mint_prefix, sr.data["label"], sr.source_id)
        for qid, el in elements.items():
            el["source_type"] = self._source_type(el)
            sr = SourceRecord(el, el["source_type"], qid)
            rule = self.classify(ctx, sr)
            if rule is None:
                continue
            classified.append((sr, rule))
            guid_map[qid] = mint_ark(
                naan, rule.mint_prefix, el["label"] or el["local"], qid)

        ctx.records = [Record(data=sr.data, rule=rule, source_id=sr.source_id)
                       for sr, rule in classified]
        ctx.extras.update(
            naan=naan, guid_map=guid_map, relations=relations,
            parent_of=parent_of, sender_agent_by_bundle=sender_agent,
            elements=elements, cpm_prefixes=prefixes, cpm_default_ns=default_ns,
            bundle_file_of={qid: el["bundle_file"] for qid, el in elements.items()},
        )

    @staticmethod
    def _merge_element(elements: dict, stmt, bundle_id: str, file_id):
        """Merge one entity/activity/agent statement into the element table —
        the same qualified id in several bundles is ONE element (that identity
        is exactly how CPM chains bundles)."""
        qid = stmt.args[0]
        el = elements.setdefault(qid, {
            "qid": qid, "local": qid.rsplit(":", 1)[-1], "kind": stmt.name,
            "label": None, "cpm_type": None, "attrs": {},
            "bundle_id": bundle_id, "bundle_file": file_id,
        })
        if el["bundle_file"] is None and file_id is not None:
            el["bundle_file"], el["bundle_id"] = file_id, bundle_id
        if stmt.name == "activity" and el["kind"] == "entity":
            el["kind"] = "activity"        # stub created from a relation
        for key, value, _datatype in stmt.attrs:
            if key == "prov:label":
                el["label"] = el["label"] or str(value)
            elif key == "prov:type" and str(value).startswith("cpm:"):
                el["cpm_type"] = el["cpm_type"] or str(value)[len("cpm:"):]
            elif key in el["attrs"] and el["attrs"][key] != value:
                prev = el["attrs"][key]
                el["attrs"][key] = (prev if isinstance(prev, list) else [prev]) + [value]
            else:
                el["attrs"][key] = value

    @staticmethod
    def _source_type(el: dict) -> str:
        if el["kind"] == "activity":
            return _ACTIVITY_SOURCE_TYPE.get(el["cpm_type"], "activity")
        if el["kind"] == "agent":
            return "agent"
        return "entity"

    def link(self, ctx: Context):
        out, guid_map = ctx.out_nodes, ctx.extras["guid_map"]

        def node_of(qid):
            ark = guid_map.get(qid)
            return (ark, out.get(ark)) if ark else (None, None)

        for name, args, _bundle in ctx.extras["relations"]:
            a = list(args) + [None, None]
            if name == "used":
                act_ark, act = node_of(a[0])
                ent_ark, ent = node_of(a[1])
                if not act or not ent:
                    continue
                if "https://w3id.org/EVI#Computation" in _types_of(act):
                    _append_ref(act, "usedDataset", ent_ark)
                    _append_ref(ent, "usedByComputation", act_ark)
                else:                                  # plain prov:Activity (transfer)
                    _append_ref(act, "prov:used", ent_ark)
            elif name == "wasGeneratedBy":
                ent_ark, ent = node_of(a[0])
                act_ark, act = node_of(a[1])
                if not act or not ent:
                    continue
                _append_ref(ent, "generatedBy", act_ark)
                _append_ref(act, "generated", ent_ark)
            elif name == "wasDerivedFrom":
                d_ark, d = node_of(a[0])
                s_ark, s = node_of(a[1])
                if d and s:
                    _append_ref(d, "derivedFrom", s_ark)
            elif name == "specializationOf":
                s_ark, s = node_of(a[0])
                g_ark, g = node_of(a[1])
                if s and g:
                    _append_ref(s, "prov:specializationOf", g_ark)
            elif name == "wasAttributedTo":
                e_ark, e = node_of(a[0])
                ag_ark, ag = node_of(a[1])
                if e and ag:
                    _append_ref(e, "prov:wasAttributedTo", ag_ark)
            elif name == "wasAssociatedWith":
                act_ark, act = node_of(a[0])
                ag_ark, ag = node_of(a[1])
                if act and ag:
                    _append_ref(act, "prov:wasAssociatedWith", ag_ark)
            elif name == "wasInvalidatedBy":
                e_ark, e = node_of(a[0])
                act_ark, act = node_of(a[1])
                if e and act:
                    _append_ref(e, "prov:wasInvalidatedBy", act_ark)
            elif name == "hadMember":
                c_ark, c = node_of(a[0])
                m_ark, m = node_of(a[1])
                if c and m:
                    _append_ref(c, "hasPart", m_ark)

        for sub_qid, main_qid in ctx.extras["parent_of"].items():
            sub_ark, sub = node_of(sub_qid)
            main_ark, main = node_of(main_qid)
            if sub and main:
                _append_ref(sub, "isPartOf", main_ark)

        # Bundle membership: each element is subjectOf its bundle's registered
        # CPMProvenanceFile Dataset (the file DESCRIBES the element — the
        # profile's own `about` link, inverted; isPartOf would wrongly claim
        # containment and hide every element from crate-level output derivation).
        for qid, file_id in ctx.extras["bundle_file_of"].items():
            el_ark, el = node_of(qid)
            file_ark = guid_map.get(file_id)
            if el and file_ark:
                _append_ref(el, "subjectOf", file_ark)

    def assemble(self, ctx: Context):
        from fairscape_models.rocrate import ROCrateV1_2

        root = ctx.root
        naan = ctx.extras["naan"]
        meta = ctx.extras["root_meta"]
        root_name = root.get("name") or "CPM provenance RO-Crate"
        root_ark = mint_ark(naan, "cpm-rocrate", root_name, root.get("@id", "./"))
        root_out = {
            "@id": root_ark,
            "@type": ["Dataset", "https://w3id.org/EVI#ROCrate"],
            "name": root_name,
            "description": root.get("description")
                or f"EVI RO-Crate converted from the CPM RO-Crate '{root_name}'.",
            "keywords": meta["keywords"] or ["cpm", "provenance"],
            "author": meta["author"] or "Unknown",
            "version": str(root.get("version") or "0.1.0"),
            "license": root.get("license") or "Unknown",
            "datePublished": root.get("datePublished"),
            "conformsTo": ([{"@id": u} for u in _ref_ids(root.get("conformsTo"))]
                           + [{"@id": FAIRSCAPE_PROFILE}]),
            "hasPart": [{"@id": ark} for ark in ctx.order],
            "identifier": root.get("@id"),
            "fromCPM": True,
            "cpmPrefixes": ctx.extras["cpm_prefixes"],
            "cpmDefaultNamespace": ctx.extras["cpm_default_ns"],
        }
        root_out = {k: v for k, v in root_out.items() if v not in (None, "", [])}

        out_crate = {
            "@context": CONTEXT_IMPORT,
            "@graph": [
                {
                    "@id": "ro-crate-metadata.json",
                    "@type": "CreativeWork",
                    "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
                    "about": {"@id": root_ark},
                },
                root_out,
                *[ctx.out_nodes[ark] for ark in ctx.order],
            ],
        }
        if ctx.extras.get("validate", True):
            ROCrateV1_2.model_validate(copy.deepcopy(out_crate))
        return out_crate

    # ------------------------------------------------------------------------
    # Export: EVI crate -> CPM provenance document
    # ------------------------------------------------------------------------

    def export(self, source, options: dict):
        return export_convert(source, self, options or {})


# ============================================================================
# Export driver
# ============================================================================

_ENTITY_KINDS = ("Dataset", "MLModel", "Software", "Instrument", "Sample")
_AGENT_KINDS = ("Organization", "Person")


def _local_name(node) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", str(node.get("name") or "entity")).strip("_")
    tail = re.sub(r"[^a-z0-9]", "", str(node.get("@id", ""))[-8:])
    return f"{base}_{tail}" if tail else base


def _export_qn(node) -> str:
    ident = node.get("identifier")
    if isinstance(ident, str) and _QN_RE.match(ident) and not ident.startswith("ark:"):
        return ident
    return _local_name(node)


def _export_attrs(node) -> list:
    attrs = []
    if node.get("name"):
        attrs.append(("prov:label", str(node["name"]), None))
    if str(node.get("additionalType") or "").startswith("cpm:"):
        attrs.append(("prov:type", node["additionalType"], None))
    for pv in node.get("additionalProperty") or []:
        if isinstance(pv, dict) and pv.get("name") is not None:
            attrs.append((str(pv["name"]), pv.get("value"), None))
    for key in ("sha256", "hash", "md5"):
        value = node.get(key)
        if isinstance(value, str):
            attrs.append((key, value, None))
    url = node.get("contentUrl")
    if isinstance(url, str):
        attrs.append(("filepath", url[len("file://"):] if url.startswith("file://") else url, None))
    params = node.get("parameter") or []
    for param in [params] if isinstance(params, str) else params:
        # Only clean key=value pairs (our own import writes these); free-text
        # parameter descriptors (e.g. wrroc's) don't survive as PROV attrs.
        if isinstance(param, str) and re.match(r"^[\w:.-]+=", param):
            k, v = param.split("=", 1)
            attrs.append((k, v, None))
    return attrs


def export_convert(crate: dict, plugin, options: dict):
    graph = crate.get("@graph", [])
    root = next((n for n in graph if _kind(n) == "ROCrate"), {})
    by_id = {n["@id"]: n for n in graph if n.get("@id")}

    # A crate imported from CPM carries its original typing; only born-EVI
    # crates get fresh cpm:mainActivity / senderConnector / externalInput calls.
    from_cpm = bool(root.get("fromCPM"))
    bundle_file_ids = {n["@id"] for n in graph
                       if n.get("additionalType") in _CPM_FILE_TYPES}
    bundle_ident_of_file = {n["@id"]: n.get("cpmBundleId")
                            for n in graph if n.get("cpmBundleId")}
    default_bundle = options.get("bundle_id") or "provenance"

    # ---- assign each node a qualified name and a bundle --------------------
    qn_of, bundle_of, exportable = {}, {}, {}
    for node in graph:
        kind = _kind(node)
        nid = node.get("@id")
        if node is root or nid in bundle_file_ids or nid == "ro-crate-metadata.json":
            continue
        is_activity = kind in ("Computation", "Activity", "Experiment")
        is_entity = kind in _ENTITY_KINDS
        is_agent = kind in _AGENT_KINDS and (
            str(node.get("additionalType") or "").startswith("cpm:"))
        if not (is_activity or is_entity or is_agent):
            continue
        exportable[nid] = ("activity" if is_activity
                           else "agent" if is_agent else "entity")
        qn_of[nid] = _export_qn(node)
        bundle = default_bundle
        for ref in _ref_ids(node.get("subjectOf")):
            if ref in bundle_ident_of_file and bundle_ident_of_file[ref]:
                bundle = bundle_ident_of_file[ref]
                break
        bundle_of[nid] = bundle

    # Agents referenced by prov:wasAttributedTo / prov:wasAssociatedWith join in.
    for node in graph:
        for key in ("prov:wasAttributedTo", "prov:wasAssociatedWith"):
            for ref in _ref_ids(node.get(key)):
                target = by_id.get(ref)
                if target and ref not in exportable and _kind(target) in _AGENT_KINDS:
                    exportable[ref] = "agent"
                    qn_of[ref] = _export_qn(target)
                    bundle_of[ref] = bundle_of.get(node.get("@id"), default_bundle)

    computation_ids = {nid for nid, k in exportable.items()
                       if k == "activity" and _kind(by_id[nid]) in ("Computation", "Experiment")}
    generated_ids = {ref for nid in exportable
                     for ref in _ref_ids(by_id[nid].get("generatedBy"))}

    # The cpm prefix URI is the one published CPM bundles bind (e.g. the
    # RationAI/MUNI crates: https://zenodo.org/records/7924183).
    prefixes = dict(root.get("cpmPrefixes") or {})
    if not from_cpm:
        prefixes.setdefault(
            "cpm", "https://www.commonprovenancemodel.org/cpm-namespace-v1-0/")
    doc = provn.Document(
        prefixes=prefixes,
        default_ns=root.get("cpmDefaultNamespace") or "http://example.org/",
    )
    bundles: dict[str, provn.Bundle] = {}

    def bundle_for(nid):
        ident = bundle_of.get(nid, default_bundle)
        if ident not in bundles:
            bundles[ident] = provn.Bundle(ident)
            doc.bundles.append(bundles[ident])
        return bundles[ident]

    def stmt(nid, name, args, attrs=()):
        bundle_for(nid).statements.append(provn.Statement(name, args, list(attrs)))

    # ---- element statements ------------------------------------------------
    for nid, role in exportable.items():
        node, qn = by_id[nid], qn_of[nid]
        attrs = _export_attrs(node)
        if role == "activity":
            fresh = not from_cpm and not str(node.get("additionalType") or "").startswith("cpm:")
            top_level = not any(r in computation_ids
                                for r in _ref_ids(node.get("isPartOf")))
            if fresh and nid in computation_ids and top_level:
                attrs.append(("prov:type", "cpm:mainActivity", None))
            children = [qn_of[c] for c in computation_ids
                        if nid in _ref_ids(by_id[c].get("isPartOf")) and c in qn_of]
            attrs.extend(("dct:hasPart", c, None) for c in sorted(children))
            stmt(nid, "activity", [qn, None, None], attrs)
        elif role == "agent":
            stmt(nid, "agent", [qn], attrs)
        else:
            fresh = not from_cpm and not str(node.get("additionalType") or "").startswith("cpm:")
            if fresh:
                used_by = _ref_ids(node.get("usedByComputation"))
                if node.get("generatedBy") and not used_by:
                    attrs.append(("prov:type", "cpm:senderConnector", None))
                elif used_by and not node.get("generatedBy"):
                    attrs.append(("prov:type", "cpm:externalInput", None))
            stmt(nid, "entity", [qn], attrs)

    # ---- relation statements ----------------------------------------------
    seen = set()

    def rel(owner, name, *qids):
        key = (name, qids)
        if key in seen or any(q is None for q in qids):
            return
        seen.add(key)
        pad = {"used": 3, "wasGeneratedBy": 3, "wasDerivedFrom": 5,
               "wasInvalidatedBy": 3}.get(name, len(qids))
        args = list(qids) + [None] * (pad - len(qids))
        stmt(owner, name, args)

    for nid, role in exportable.items():
        node = by_id[nid]
        if role == "activity":
            for key in ("usedDataset", "usedSoftware", "usedMLModel", "prov:used", "used"):
                for ref in _ref_ids(node.get(key)):
                    rel(nid, "used", qn_of[nid], qn_of.get(ref))
            for ref in _ref_ids(node.get("generated")):
                if ref not in generated_ids:
                    rel(nid, "wasGeneratedBy", qn_of.get(ref), qn_of[nid])
            for ref in _ref_ids(node.get("prov:wasAssociatedWith")):
                rel(nid, "wasAssociatedWith", qn_of[nid], qn_of.get(ref))
        else:
            for ref in _ref_ids(node.get("generatedBy")):
                rel(nid, "wasGeneratedBy", qn_of[nid], qn_of.get(ref))
            for key in ("derivedFrom", "prov:wasDerivedFrom"):
                for ref in _ref_ids(node.get(key)):
                    rel(nid, "wasDerivedFrom", qn_of[nid], qn_of.get(ref))
            for ref in _ref_ids(node.get("prov:specializationOf")):
                rel(nid, "specializationOf", qn_of[nid], qn_of.get(ref))
            for ref in _ref_ids(node.get("prov:wasAttributedTo")):
                rel(nid, "wasAttributedTo", qn_of[nid], qn_of.get(ref))
            for ref in _ref_ids(node.get("prov:wasInvalidatedBy")):
                rel(nid, "wasInvalidatedBy", qn_of[nid], qn_of.get(ref))

    if options.get("serialization") == "provn":
        return provn.provn_dumps(doc)
    return provn.provjson_dumps(doc)
