#!/usr/bin/env python3
"""A plugin bundles its CSV mapping with the Python it references by name.

.. note:: Legacy surface. New converters subclass ``core.plugin.PluginBase``
   (same contract, named methods instead of a hooks dict) — see
   ``docs/NEW-PLUGIN.md``. This dataclass is kept because the engine's contract
   is defined by its attribute surface, which ``PluginBase`` duck-types.

Every converter is a ``Plugin``: the folder of CSVs (loaded into a ``Mapping``)
plus the named parsers and hooks that the CSV cells point at. The engine takes a
``Plugin`` and runs it; there is no per-workflow engine, only per-workflow
parsers/hooks registered here.

Parsers share one signature (see ``MAPPING-SCHEMA.md``)::

    fn(value, rule, ctx) -> parsed value | None

Hooks are the orchestration stages (``pre`` / ``link`` / ``assemble`` and the
optional ``select_rules`` / ``finalize`` overrides). A plugin supplies only the
stages it needs; the engine fills in defaults for the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .loader import load_mapping
from .schema import Mapping


@dataclass
class Plugin:
    """One converter: its mapping + the code its CSVs name."""

    name: str
    mapping_dir: Path
    import_parsers: dict[str, Callable] = field(default_factory=dict)
    export_parsers: dict[str, Callable] = field(default_factory=dict)
    hooks: dict[str, Callable] = field(default_factory=dict)
    mapping: Mapping = None  # populated in __post_init__

    def __post_init__(self):
        # Validate the CSV parser names against the registries at load time, so a
        # typo in a CSV fails here rather than mid-conversion.
        self.mapping = load_mapping(
            self.mapping_dir,
            import_parser_names=set(self.import_parsers),
            export_parser_names=set(self.export_parsers),
        )

    def hook(self, stage: str, default: Callable = None) -> Callable:
        """The plugin's hook for ``stage``, or ``default`` (a no-op if omitted)."""
        return self.hooks.get(stage, default if default is not None else (lambda ctx: None))
