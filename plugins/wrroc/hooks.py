#!/usr/bin/env python3
"""WRROC <-> EVI: ``WrrocPlugin`` orchestration.

Import (WRROC -> EVI) runs through the shared pipeline: ``pre`` classifies the
graph (via the shared ``classify_node`` + this plugin's named discriminators)
and mints ARKs, the engine maps each node, ``link`` adds the parent / inverse
edges, ``assemble`` builds the root + graph. Export (EVI -> Process Run Crate)
is bespoke (custom @type decisions + PropertyValue re-expansion) so it is one
``export`` override composing the shared ``apply_export_rules`` kernel — same
CSVs, same parser signature, just its own assembly. Ported from
``wrroc_to_evi.py`` and ``evi_to_wrroc.py``.
"""

from __future__ import annotations

import copy

from ...core import (Context, PluginBase, Record, SourceRecord,
                     apply_export_rules, roundtrip)
from .parsers import (DEFAULT_NAAN, EXPORT_PARSERS, IMPORT_PARSERS, agent_name,
                      listify, mint_ark, ref_ids, slugify, types_of)

# Profile config is workflow-specific (not property data), so it stays Python.
PROFILES = {
    "wrroc_prefixes": [
        "https://w3id.org/ro/wfrun/process",
        "https://w3id.org/ro/wfrun/workflow",
        "https://w3id.org/ro/wfrun/provenance",
    ],
    "fairscape_profile": "https://w3id.org/fairscape/profile/0.1",
    "export_conformsTo": ["https://w3id.org/ro/wfrun/process/0.5"],
    "export_crate_spec": "https://w3id.org/ro/crate/1.1",
}

CONTEXT_IMPORT = {
    "@vocab": "https://schema.org/",
    "evi": "https://w3id.org/EVI#",
    "prov": "http://www.w3.org/ns/prov#",
}

CONTEXT_EXPORT = [
    "https://w3id.org/ro/crate/1.1/context",
    {
        "ParameterConnection": "https://w3id.org/ro/terms/workflow-run#ParameterConnection",
        "connection": "https://w3id.org/ro/terms/workflow-run#connection",
        "sha1": "https://w3id.org/ro/terms/workflow-run#sha1",
        "sourceParameter": "https://w3id.org/ro/terms/workflow-run#sourceParameter",
        "targetParameter": "https://w3id.org/ro/terms/workflow-run#targetParameter",
    },
]


# ============================================================================
# Shared helpers
# ============================================================================

def _find_descriptor(graph):
    for node in graph:
        if node.get("@id") == "ro-crate-metadata.json":
            return node
    raise ValueError("no ro-crate-metadata.json descriptor in @graph")


def _check_conformance(root, prefixes):
    urls = ref_ids(root.get("conformsTo"))
    if not any(u.startswith(p) for u in urls for p in prefixes):
        raise ValueError(
            f"crate root conformsTo {urls} matches no Workflow Run RO-Crate profile ({prefixes})")
    return urls


def _instrument_is_workflow(node, ctx) -> bool:
    """A CreateAction is the parent run when its instrument is the crate's
    mainEntity or is typed ComputationalWorkflow (else it is a tool run).
    Reads ``ctx.by_id`` / ``ctx.extras['main_entity']``, set by ``pre`` before
    classification."""
    main_entity = ctx.extras.get("main_entity")
    instrument_ids = ref_ids(node.get("instrument"))
    return any(
        iid == main_entity
        or "ComputationalWorkflow" in types_of(ctx.by_id.get(iid, {}))
        for iid in instrument_ids)


DISCRIMINATORS = {
    "instrument_is_workflow": _instrument_is_workflow,
    "instrument_is_tool": lambda node, ctx: not _instrument_is_workflow(node, ctx),
}


def _fallback_agent(organize_actions, root):
    for oa in organize_actions:
        agent_ids = ref_ids(oa.get("agent"))
        if agent_ids:
            return {"@id": agent_ids[0]}
        if isinstance(oa.get("agent"), str) and oa["agent"].strip():
            return oa["agent"].strip()
    author = root.get("author") or root.get("creator")
    author_ids = ref_ids(author)
    if author_ids:
        return {"@id": author_ids[0]}
    if isinstance(author, str) and author.strip():
        return author.strip()
    return "Unknown"


def _kind(node):
    node_types = types_of(node)
    last = str(node_types[-1]) if node_types else ""
    return last.split("#")[-1].split("/")[-1].split(":")[-1]


# ============================================================================
# The plugin
# ============================================================================

class WrrocPlugin(PluginBase):
    """Workflow Run RO-Crate <-> FAIRSCAPE EVI RO-Crate."""

    name = "wrroc"
    import_parsers = IMPORT_PARSERS
    export_parsers = EXPORT_PARSERS
    discriminators = DISCRIMINATORS

    def pre(self, ctx: Context):
        """Classify the WRROC graph and mint ARKs (full-control override:
        classification and id minting interleave)."""
        crate = ctx.source
        naan = ctx.extras.get("naan", DEFAULT_NAAN)
        graph = crate.get("@graph", [])
        ctx.by_id = {n["@id"]: n for n in graph if n.get("@id")}

        descriptor = _find_descriptor(graph)
        root = ctx.by_id[descriptor["about"]["@id"]]
        ctx.root = root
        wrroc_conforms = _check_conformance(root, PROFILES["wrroc_prefixes"])
        main_ids = ref_ids(root.get("mainEntity"))
        main_entity = main_ids[0] if main_ids else None
        # The instrument_is_workflow discriminator reads this during classify.
        ctx.extras["main_entity"] = main_entity

        classified, agent_nodes, organize_actions = [], [], []
        for node in graph:
            if node is descriptor or node is root:
                continue
            rule = self.classify(ctx, SourceRecord(node, "", node.get("@id", "")))
            if rule is None:
                continue
            if rule.level == "agent":
                agent_nodes.append(node)
            elif rule.level == "drop":
                if "OrganizeAction" in types_of(node):
                    organize_actions.append(node)
            else:
                classified.append((node, rule))

        fallback_agent = _fallback_agent(organize_actions, root)
        workflow_actions = [n for n, r in classified if r.level == "workflow"]
        workflow_end_time = workflow_actions[0].get("endTime") if workflow_actions else None
        guid_map = {
            node["@id"]: mint_ark(
                rule.mint_prefix,
                node.get("alternateName") or node.get("name") or node["@id"].rstrip("/").split("/")[-1],
                node["@id"], naan)
            for node, rule in classified
        }

        ctx.extras.update(
            naan=naan,
            wrroc_conforms=wrroc_conforms,
            main_entity=main_entity,
            fallback_agent=fallback_agent,
            workflow_end_time=workflow_end_time,
            guid_map=guid_map,
            agents=agent_nodes,
            organize_actions=organize_actions,
            workflow_actions=workflow_actions,
        )
        ctx.records = [Record(data=node, rule=rule, source_id=node["@id"])
                       for node, rule in classified]

    def link(self, ctx: Context):
        """Parent isPartOf/usedSoftware edges + generatedBy/usedByComputation inverses."""
        out_nodes = ctx.out_nodes
        guid_map = ctx.extras["guid_map"]
        workflow_actions = ctx.extras["workflow_actions"]
        organize_actions = ctx.extras["organize_actions"]

        if len(workflow_actions) == 1:
            parent_ark = guid_map[workflow_actions[0]["@id"]]
            for rec in ctx.records:
                if rec.rule.level == "tool":
                    out_nodes[guid_map[rec.source_id]]["isPartOf"] = [{"@id": parent_ark}]
            for oa in organize_actions:
                for iid in ref_ids(oa.get("instrument")):
                    if iid in guid_map:
                        used = out_nodes[parent_ark].setdefault("usedSoftware", [])
                        ref = {"@id": guid_map[iid]}
                        if ref not in used:
                            used.append(ref)

        for out in out_nodes.values():
            types = out["@type"] if isinstance(out["@type"], list) else [out["@type"]]
            if not str(types[-1]).endswith("Computation"):
                continue
            comp_ref = {"@id": out["@id"]}
            for ref in out.get("generated", []):
                target = out_nodes.get(ref["@id"])
                if target is not None:
                    target.setdefault("generatedBy", []).append(comp_ref)
            for key in ("usedDataset", "usedSoftware"):
                for ref in out.get(key, []):
                    target = out_nodes.get(ref["@id"])
                    if target is not None:
                        target.setdefault("usedByComputation", []).append(comp_ref)

    def assemble(self, ctx: Context):
        from fairscape_models.rocrate import ROCrateV1_2

        root = ctx.root
        by_id = ctx.by_id
        naan = ctx.extras["naan"]
        fallback_agent = ctx.extras["fallback_agent"]
        workflow_actions = ctx.extras["workflow_actions"]
        main_entity = ctx.extras["main_entity"]

        root_name = (root.get("name")
                     or (workflow_actions[0].get("name") if workflow_actions else None)
                     or (by_id.get(main_entity, {}).get("name") if main_entity else None)
                     or "Workflow Run RO-Crate")
        root_ark = mint_ark("rocrate", root_name, root.get("@id", "./"), naan)
        root_out = {
            "@id": root_ark,
            "@type": ["Dataset", "https://w3id.org/EVI#ROCrate"],
            "name": root_name,
            "description": root.get("description")
                or f"EVI RO-Crate converted from the Workflow Run RO-Crate '{root_name}'.",
            "keywords": [str(k) for k in listify(root.get("keywords"))] or ["wrroc", "workflow-run"],
            "version": str(root.get("version") or "0.1.0"),
            "license": root.get("license"),
            "author": agent_name(fallback_agent, by_id),
            "datePublished": root.get("datePublished"),
            "conformsTo": ([{"@id": u} for u in ref_ids(root.get("conformsTo"))]
                           + [{"@id": PROFILES["fairscape_profile"]}]),
            "hasPart": [{"@id": ark} for ark in ctx.order],
            "identifier": root.get("@id"),
            "fromWRROC": True,
            "wrrocConformsTo": ctx.extras["wrroc_conforms"],
        }

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
                *ctx.extras["agents"],
            ],
        }

        if ctx.extras.get("validate", True):
            ROCrateV1_2.model_validate(copy.deepcopy(out_crate))
        return out_crate

    def export(self, source, options: dict) -> dict:
        """EVI -> Process Run Crate: bespoke driver (see export_convert below)."""
        return export_convert(source, self)


# ============================================================================
# Export (EVI -> Process Run Crate) — bespoke, composes apply_export_rules
# ============================================================================

def export_convert(crate: dict, plugin) -> dict:
    mapping = plugin.mapping
    graph = crate.get("@graph", [])
    root = next(n for n in graph if _kind(n) == "ROCrate")
    from_wrroc = bool(root.get("fromWRROC"))
    restore = roundtrip.restore_map(graph) if from_wrroc else {}

    persons = []

    def mint_person(name):
        pid = f"#agent-{slugify(name)}"
        if not any(p["@id"] == pid for p in persons):
            persons.append({"@id": pid, "@type": "Person", "name": name})
        return {"@id": pid}

    ctx = Context(plugin, "export", crate)
    ctx.extras["restore"] = restore
    ctx.extras["mint_person"] = mint_person

    actions, data_entities, software_entities, carried = [], [], [], []
    for node in graph:
        kind = _kind(node)
        if node is root or kind == "CreativeWork":
            continue
        out_id = restore.get(node.get("@id"), node.get("@id"))
        if kind == "Computation":
            action = {"@id": out_id, "@type": "CreateAction",
                      **apply_export_rules(node, mapping.export_rules_by_target("Computation"), ctx)}
            for pname, pvalue in (node.get("parameters") or {}).items():
                pv = {"@id": f"#pv-{slugify(pname)}-{slugify(node['@id'])[-7:]}",
                      "@type": "PropertyValue", "name": pname, "value": pvalue}
                carried.append(pv)
                action.setdefault("object", []).append({"@id": pv["@id"]})
            actions.append(action)
        elif kind == "Dataset":
            entity = {"@id": out_id,
                      "@type": "Dataset" if node.get("hasPart") else "File",
                      "name": node.get("name"),
                      **apply_export_rules(node, mapping.export_rules_by_target("Dataset"), ctx)}
            data_entities.append(entity)
        elif kind == "Software":
            software_entities.append(
                {"@id": out_id, "@type": "SoftwareApplication",
                 **apply_export_rules(node, mapping.export_rules_by_target("Software"), ctx)})
        elif kind in ("Person", "Organization"):
            carried.append(dict(node))

    process_profile = PROFILES["export_conformsTo"][0]
    root_out = {
        "@id": "./",
        "@type": "Dataset",
        "conformsTo": [{"@id": u} for u in PROFILES["export_conformsTo"]],
        "name": root.get("name"),
        "description": root.get("description"),
        "datePublished": root.get("datePublished"),
        "license": root.get("license"),
        "hasPart": [{"@id": e["@id"]} for e in data_entities + software_entities
                    if "#" not in e["@id"]],
        "mentions": [{"@id": a["@id"]} for a in actions],
    }
    root_out = {k: v for k, v in root_out.items() if v not in (None, [], "")}

    return {
        "@context": CONTEXT_EXPORT,
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": {"@id": PROFILES["export_crate_spec"]},
                "about": {"@id": "./"},
            },
            root_out,
            {"@id": process_profile, "@type": "CreativeWork",
             "name": "Process Run Crate", "version": process_profile.rsplit("/", 1)[-1]},
            *software_entities,
            *data_entities,
            *actions,
            *persons,
            *carried,
        ],
    }
