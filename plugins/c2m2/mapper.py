#!/usr/bin/env python3
"""C2M2 datapackage plumbing + the non-row element builders.

Ported verbatim from ``c2m2-rocrate/src/base.py`` (the v0.1 mapper), minus the
v0.1-only paths that the mapping-driven converter superseded (``create_rocrate``,
``_root_element``, ``_file_entities`` — file explosion is a ``file`` mapping now).
Kept: datapackage reading, the per-table Dataset + evi:Schema reflection layer
(driven off the Frictionless descriptor, not per-record rules), the preservation
file nodes, the Computation/Software provenance pair, ``_resolve_metadata``, and
the ``_dump``/``_prune_none`` serialization the whole crate depends on.

One deliberate change: ``_read_tsv`` caches per table (the old engine re-parsed
each TSV up to 3x across the guid-map / association / explode passes). Rows are
never mutated downstream, so sharing the dicts is safe.
"""
import csv
import json
import pathlib
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from fairscape_models.computation import Computation
from fairscape_models.dataset import Dataset, _count_csv
from fairscape_models.schema import Schema
from fairscape_models.software import Software

# Full @context for the crate (matches the worked example). `cfde:` is a placeholder
# term namespace — register a real CFDE term URI before publication (design §8).
CONTEXT = {
    "@vocab": "https://schema.org/",
    "evi": "https://w3id.org/EVI#",
    "prov": "http://www.w3.org/ns/prov#",
    "cfde": "https://w3id.org/cfde/terms#",
}

DEFAULT_NAAN = "59853"
DEFAULT_LICENSE = "https://creativecommons.org/licenses/by/4.0/"

# Frictionless field types that map straight onto the Property.type enum
# ({integer, number, string, array, boolean, object}). Everything else
# (datetime/date/time/year/duration/geopoint/...) degrades to "string".
_PASSTHROUGH_TYPES = {"integer", "number", "string", "array", "boolean", "object"}

DATAPACKAGE_NAME = "C2M2_datapackage.json"
SQLITE_NAME = "C2M2_datapackage.sqlite"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-").lower()


def _prop_type(frictionless_type: Optional[str]) -> str:
    return frictionless_type if frictionless_type in _PASSTHROUGH_TYPES else "string"


def _as_list(value: Any) -> List[Any]:
    """C2M2 datapackage primaryKey / foreignKey fields are string-or-array; normalize."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _value_url_for_field(field: Dict[str, Any]) -> Optional[str]:
    """Infer an ontology base for a controlled-vocabulary column from its description."""
    upper = (field.get("description") or "").upper()
    if "EDAM" in upper:
        return "http://edamontology.org/"
    if any(tok in upper for tok in ("UBERON", "OBI ", "OBI.", "OBI CV", "OBO", "OBOLIBRARY")):
        return "http://purl.obolibrary.org/obo/"
    return None


def _edam_encoding_format(file_format: Optional[str]) -> Optional[str]:
    """Expand an EDAM compact id (e.g. ``format:3475``) to its ontology IRI."""
    if not file_format:
        return None
    value = file_format.strip()
    if value.startswith("format:"):
        return "http://edamontology.org/format_" + value.split(":", 1)[1]
    return None


def _prune_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _prune_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_prune_none(v) for v in value if v is not None]
    return value


def _dump(model) -> Dict[str, Any]:
    """Serialize a fairscape_models element with JSON-LD aliases, dropping None."""
    return _prune_none(model.model_dump(by_alias=True))


class C2M2Mapper:
    """Datapackage plumbing + non-row element builders for one C2M2 directory."""

    def __init__(self, datapackage_dir: Union[str, pathlib.Path]):
        self.dir = pathlib.Path(datapackage_dir)
        if not self.dir.is_dir():
            raise FileNotFoundError(f"C2M2 datapackage path is not a directory: {self.dir}")

        self.datapackage_path = self.dir / DATAPACKAGE_NAME
        if not self.datapackage_path.exists():
            raise FileNotFoundError(
                f"No {DATAPACKAGE_NAME} found in {self.dir}; not a C2M2 datapackage."
            )

        with self.datapackage_path.open("r", encoding="utf-8") as f:
            self.datapackage = json.load(f)
        self.resources: List[Dict[str, Any]] = self.datapackage.get("resources", [])
        if not self.resources:
            raise ValueError(f"{self.datapackage_path} lists no resources.")

        self.sqlite_path = self.dir / SQLITE_NAME
        self._resource_by_name = {r["name"]: r for r in self.resources}
        self._tsv_cache: Dict[str, List[Dict[str, str]]] = {}

    # -- datapackage helpers -------------------------------------------------

    def _table_path(self, table: str) -> pathlib.Path:
        resource = self._resource_by_name.get(table, {})
        return self.dir / (resource.get("path") or f"{table}.tsv")

    def _read_tsv(self, table: str) -> List[Dict[str, str]]:
        if table in self._tsv_cache:
            return self._tsv_cache[table]
        path = self._table_path(table)
        if not path.exists():
            rows: List[Dict[str, str]] = []
        else:
            with path.open("r", newline="", encoding="utf-8", errors="replace") as f:
                rows = list(csv.DictReader(f, delimiter="\t"))
        self._tsv_cache[table] = rows
        return rows

    def _populated_tables(self) -> List[str]:
        """Tables with a present TSV holding >= 1 data row (drive off real content)."""
        populated = []
        for resource in self.resources:
            table = resource["name"]
            path = self._table_path(table)
            if not path.exists():
                continue
            rows, _ = _count_csv(path, "\t")
            if rows >= 1:
                populated.append(table)
        return populated

    @staticmethod
    def _is_association(resource: Dict[str, Any]) -> bool:
        """Association (link) table: composite PK whose columns are all FK columns."""
        schema = resource.get("schema", {})
        pk = _as_list(schema.get("primaryKey"))
        if len(pk) < 2:
            return False
        fk_columns = set()
        for fk in schema.get("foreignKeys", []):
            fk_columns.update(_as_list(fk.get("fields")))
        return set(pk).issubset(fk_columns)

    # -- element builders ----------------------------------------------------

    def _schema_element(self, resource: Dict[str, Any], meta: Dict[str, Any]) -> Schema:
        table = resource["name"]
        schema = resource["schema"]
        fields = schema.get("fields", [])

        properties: Dict[str, Dict[str, Any]] = {}
        required: List[str] = []
        for index, field in enumerate(fields):
            prop = {
                "description": field.get("description") or field["name"],
                "index": index,
                "type": _prop_type(field.get("type")),
            }
            value_url = _value_url_for_field(field)
            if value_url:
                prop["value-url"] = value_url
            properties[field["name"]] = prop
            if (field.get("constraints") or {}).get("required"):
                required.append(field["name"])

        primary_key = _as_list(schema.get("primaryKey"))
        for column in primary_key:
            if column not in required:
                required.append(column)

        foreign_keys = [
            {
                "fields": _as_list(fk["fields"]),
                "reference": {
                    "resource": fk["reference"]["resource"],
                    "fields": _as_list(fk["reference"]["fields"]),
                },
            }
            for fk in schema.get("foreignKeys", [])
        ]

        element = {
            "@id": f"{meta['prefix']}-schema-{table}",
            "@type": "evi:Schema",
            "conformsTo": {"@id": "https://json-schema.org/draft/2020-12/schema"},
            "name": f"C2M2 {table} table schema",
            "description": (
                f"Column schema for the C2M2 '{table}' table, derived from "
                f"{DATAPACKAGE_NAME}. Primary key and foreign keys are preserved in the "
                f"cfde:* extension fields (fairscape's evi:Schema has no native "
                f"relational key fields)."
            ),
            "keywords": ["C2M2", "schema", table],
            "type": "object",
            "separator": "\t",
            "header": True,
            "additionalProperties": False,
            "required": required,
            "properties": properties,
            "cfde:primaryKey": primary_key,
            "cfde:foreignKeys": foreign_keys,
        }
        return Schema.model_validate(element)

    def _table_dataset(self, resource: Dict[str, Any], meta: Dict[str, Any]) -> Dataset:
        table = resource["name"]
        path = self._table_path(table)
        rows, cols = _count_csv(path, "\t")
        size = path.stat().st_size

        description = resource.get("description") or (
            f"The C2M2 '{table}' table for the {meta['dcc_label']} instance, preserved "
            f"verbatim as a TSV ({rows} data rows, {cols} columns). Its column schema "
            f"and foreign keys are described by the linked evi:Schema."
        )

        element = {
            "@id": f"{meta['prefix']}-table-{table}",
            "@type": ["prov:Entity", "https://w3id.org/EVI#Dataset"],
            "additionalType": "Dataset",
            "name": f"C2M2 {table} table ({meta['dcc_label']})",
            "description": description,
            "author": meta["author"],
            "datePublished": meta["date"],
            "keywords": ["C2M2", "table", table],
            "format": "text/tab-separated-values",
            "contentUrl": f"file:///{table}.tsv",
            "evi:Schema": {"@id": f"{meta['prefix']}-schema-{table}"},
            "rowCount": rows,
            "columnCount": cols,
            "contentSize": str(size),
            "generatedBy": {"@id": meta["conversion_guid"]},
            "isPartOf": [{"@id": meta["crate_guid"]}],
            "cfde:c2m2Table": table,
        }

        if self._is_association(resource):
            referenced = []
            seen = set()
            for fk in resource["schema"].get("foreignKeys", []):
                ref_table = fk["reference"]["resource"]
                if ref_table in meta["populated"] and ref_table not in seen:
                    seen.add(ref_table)
                    referenced.append({"@id": f"{meta['prefix']}-table-{ref_table}"})
            if referenced:
                element["cfde:referencesTable"] = referenced

        return Dataset.model_validate(element)

    def _preserved_file(self, path: pathlib.Path, guid: str, role: str,
                        fmt: str, meta: Dict[str, Any], description: str) -> Dataset:
        element = {
            "@id": guid,
            "@type": ["prov:Entity", "https://w3id.org/EVI#Dataset"],
            "additionalType": "File",
            "name": path.name,
            "description": description,
            "author": meta["author"],
            "datePublished": meta["date"],
            "keywords": ["C2M2", "preservation", role],
            "format": fmt,
            "contentUrl": f"file:///{path.name}",
            "contentSize": str(path.stat().st_size),
            "isPartOf": [{"@id": meta["crate_guid"]}],
            "cfde:role": role,
        }
        return Dataset.model_validate(element)

    def _software(self, meta: Dict[str, Any]) -> Software:
        element = {
            "@id": meta["software_guid"],
            "@type": ["prov:Entity", "https://w3id.org/EVI#Software"],
            "additionalType": "Software",
            "name": "CFDE C2M2 to RO-Crate Converter",
            "description": (
                "Reference converter that reads a C2M2 Frictionless datapackage "
                "(datapackage.json + TSVs + SQLite) and emits a FAIRSCAPE RO-Crate "
                "following the C2M2-to-ROCrate design spec."
            ),
            "author": "CFDE / FAIRSCAPE",
            "version": "0.1.0",
            "format": "text/x-python",
            "url": "https://github.com/fairscape",
            "isPartOf": [{"@id": meta["crate_guid"]}],
        }
        return Software.model_validate(element)

    def _computation(self, meta: Dict[str, Any], generated_guids: List[str],
                     used_dataset_guids: List[str]) -> Computation:
        element = {
            "@id": meta["conversion_guid"],
            "@type": ["prov:Activity", "https://w3id.org/EVI#Computation"],
            "additionalType": "Computation",
            "name": f"C2M2 to RO-Crate conversion ({meta['dcc_label']})",
            "description": (
                f"Conversion of the {meta['dcc_label']} C2M2 Frictionless datapackage "
                f"into this RO-Crate: one Dataset + evi:Schema per populated table, the "
                f"file table additionally exploded into file-level source-data entities, "
                f"and the datapackage.json + SQLite preserved verbatim."
            ),
            "runBy": meta["author"],
            "dateCreated": meta["date"],
            "command": f"python3 convert.py {self.dir} --output-path {meta['output_path']}",
            "usedSoftware": [{"@id": meta["software_guid"]}],
            "usedDataset": [{"@id": g} for g in used_dataset_guids],
            "generated": [{"@id": g} for g in generated_guids],
            "isPartOf": [{"@id": meta["crate_guid"]}],
        }
        return Computation.model_validate(element)

    # -- resolved metadata -----------------------------------------------------

    def _resolve_metadata(self, author, publisher, date_published, naan):
        dcc_rows = self._read_tsv("dcc")
        dcc_row = dcc_rows[0] if dcc_rows else {}
        namespaces = [r.get("id") for r in self._read_tsv("id_namespace") if r.get("id")]

        # Top-level project: DCC-level metadata that seeds the crate name/description/identifier
        # when the caller supplies no explicit override. Take the first row (per the dcc pattern);
        # in the CFDE samples the first project row is the root of the project_in_project hierarchy.
        project_rows = self._read_tsv("project")
        project_row = project_rows[0] if project_rows else {}

        def _clean(value):
            return (value or "").strip() or None

        slug = _slug(dcc_row.get("dcc_abbreviation") or self.dir.name)
        prefix = f"ark:{naan}/{slug}-c2m2"

        dcc_label = dcc_row.get("dcc_name") or self.dir.name
        resolved_author = author or f"CFDE / {dcc_label} DCC"
        resolved_date = date_published or datetime.now(timezone.utc).date().isoformat()

        is_part_of = [{"@id": "https://cfde.cloud"}]
        for ns in namespaces:
            is_part_of.append({"@id": f"ark:{naan}/{ns}"})

        return {
            "crate_guid": prefix,
            "prefix": prefix,
            "conversion_guid": f"{prefix}-conversion",
            "software_guid": f"{prefix}-converter-software",
            "dcc_label": dcc_label,
            "author": resolved_author,
            "publisher": publisher or "NIH Common Fund Data Ecosystem",
            "date": resolved_date,
            "isPartOf": is_part_of,
            "project_name": _clean(project_row.get("name")),
            "project_description": _clean(project_row.get("description")),
            "project_identifier": _clean(project_row.get("persistent_id")),
        }

    def _copy_preservation_files(self, output_path, populated, preserve_sqlite):
        to_copy = [self._table_path(t) for t in populated]
        to_copy.append(self.datapackage_path)
        if preserve_sqlite:
            to_copy.append(self.sqlite_path)
        for source in to_copy:
            destination = output_path / source.name
            if source.resolve() == destination.resolve():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, destination)
