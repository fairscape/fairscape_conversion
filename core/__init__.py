#!/usr/bin/env python3
"""Unified converter core — one mapping format, one kernel, per-plugin code.

Public API used by the plugins:

    from fairscape_conversion.core import (Plugin, Context, Record, Mapping,
                            run_pipeline, apply_import_rules, apply_export_rules,
                            run_import_parser, run_export_parser,
                            interpolate, roundtrip)
"""

from . import parsers, roundtrip
from .engine import (Context, Record, apply_export_rules, apply_import_rules,
                     interpolate, run_export_parser, run_import_parser,
                     run_pipeline)
from .loader import load_mapping
from .plugin import PluginBase
from .records import (SourceRecord, classify_node, records_from_graph,
                      records_from_items, types_of)
from .registry import Plugin
from .schema import (AssocRule, CvBase, EntityRule, Mapping, PropertyRule,
                     split_pipe)

__all__ = [
    "Plugin", "PluginBase", "Context", "Record", "Mapping",
    "SourceRecord", "classify_node", "records_from_items", "records_from_graph",
    "types_of",
    "EntityRule", "PropertyRule", "AssocRule", "CvBase", "split_pipe",
    "load_mapping", "run_pipeline",
    "apply_import_rules", "apply_export_rules",
    "run_import_parser", "run_export_parser",
    "interpolate", "parsers", "roundtrip",
]
