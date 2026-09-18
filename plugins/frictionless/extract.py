"""frictionless plugin extraction — a Data Package on disk -> plain records.

The I/O half (the ``plugins/redcap/extract.py`` mould): open
``datapackage.json``, note which resource paths are local files and how big
they are, and hand a plain dict to the mapping so ``convert("import",
records)`` stays a pure function and the golden test hermetic.

A Data Package (https://datapackage.org, formerly frictionlessdata.io) is
the container a lot of social-science and public-health data ships in:
one descriptor listing *resources* (files or inline data), each optionally
carrying a Table Schema — typed fields with constraints, primary and
foreign keys, missing-value markers. C2M2 is one specialised profile of it
and has its own plugin; this one takes any package.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date

from ...core.arks import DEFAULT_NAAN

DESCRIPTOR_NAMES = ("datapackage.json", "datapackage.yaml", "datapackage.yml")
REMOTE = ("http://", "https://", "ftp://", "s3://", "gs://")


def find_descriptor(path) -> str:
    """A directory holding a datapackage.json, or the file itself."""
    path = str(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"no such path: {path}")
    if os.path.isdir(path):
        for name in DESCRIPTOR_NAMES:
            candidate = os.path.join(path, name)
            if os.path.exists(candidate):
                return candidate
        raise FileNotFoundError(f"no datapackage.json in {path}")
    return path


def read_descriptor(path) -> dict:
    path = str(path)
    with open(path, encoding="utf-8-sig") as f:
        if path.endswith((".yaml", ".yml")):
            import yaml
            descriptor = yaml.safe_load(f)
        else:
            descriptor = json.load(f)
    if not isinstance(descriptor, dict) or not isinstance(descriptor.get("resources"), list):
        raise ValueError(f"{path}: not a Data Package descriptor (no 'resources' list)")
    return descriptor


def package_key(descriptor: dict) -> str:
    """The ARK source for the package: name@version when the package is
    named (the identity Frictionless itself uses), else a digest of the
    resources' names, paths and schemas."""
    name = descriptor.get("name")
    if name:
        return f"{name}@{descriptor.get('version', '')}"
    parts = [json.dumps({k: r.get(k) for k in ("name", "path", "schema")}, sort_keys=True)
             for r in descriptor.get("resources", [])]
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()


def _first_path(path):
    """A resource ``path`` may be a string or a list (multipart); the first
    part names the file."""
    if isinstance(path, list):
        return path[0] if path else None
    return path


def _relative(path, crate_dir) -> str:
    if crate_dir:
        try:
            return os.path.relpath(path, crate_dir)
        except ValueError:
            pass
    return os.path.basename(str(path))


def resource_record(resource: dict, base_dir, crate_dir) -> dict:
    """One resource as the mapping sees it: the descriptor entry plus what
    the disk says about the file (if it is a local one)."""
    rec = dict(resource)
    raw_path = _first_path(resource.get("path"))
    rec["path"] = raw_path
    rec["remote"] = bool(raw_path and str(raw_path).startswith(REMOTE))
    rec["inline"] = raw_path is None and "data" in resource
    rec["local_path"] = None
    rec["size"] = resource.get("bytes")
    if raw_path and not rec["remote"] and base_dir is not None:
        full = os.path.normpath(os.path.join(base_dir, raw_path))
        if os.path.exists(full):
            rec["local_path"] = _relative(full, crate_dir) if crate_dir else raw_path
            if rec["size"] is None:
                rec["size"] = os.path.getsize(full)
    elif raw_path and not rec["remote"]:
        rec["local_path"] = raw_path
    if rec["inline"]:
        rec["data"] = resource["data"]      # kept: it is the dataset
    return rec


def extract(source, *, naan=DEFAULT_NAAN, name=None, description=None, author=None,
            keywords=None, license=None, version=None, date_published=None,
            crate_dir=None) -> dict:
    """``source`` is a package directory, a descriptor path, or an already
    parsed descriptor dict (then nothing on disk is consulted)."""
    if isinstance(source, dict):
        descriptor, descriptor_path, base_dir = source, None, None
    else:
        descriptor_path = find_descriptor(source)
        descriptor = read_descriptor(descriptor_path)
        base_dir = os.path.dirname(os.path.abspath(descriptor_path))

    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    package = {k: descriptor.get(k) for k in
               ("name", "title", "description", "version", "created", "homepage",
                "id", "profile", "keywords", "licenses", "contributors", "sources")}
    package["key"] = package_key(descriptor)
    title = name or package["title"] or package["name"] or "Data Package"
    resources = [resource_record(r, base_dir, crate_dir) for r in descriptor["resources"]]

    out = {
        "settings": {
            "naan": naan,
            "name": title,
            "description": description or package["description"] or (
                f"Data Package '{title}' with {len(resources)} resource(s)"),
            "author": author or "",
            "keywords": keywords or list(package["keywords"] or []) or ["data package", "frictionless"],
            "license": license or "",
            "version": version or package["version"] or "1.0",
            "date_published": date_published or (package["created"] or "")[:10]
                              or date.today().isoformat(),
        },
        "package": package,
        "resources": resources,
        "descriptor_file": None,
    }
    if descriptor_path:
        out["descriptor_file"] = {
            "file": os.path.basename(descriptor_path),
            "local_path": _relative(descriptor_path, crate_dir) if crate_dir
                          else os.path.basename(descriptor_path),
            "size": os.path.getsize(descriptor_path),
        }
    return out
