#!/usr/bin/env python3
"""example plugin — the minimal runnable converter. Copy this folder to start yours.

A toy "memo" format (see ``input.json``) becomes a graph of schema.org Datasets.
Everything a plugin *must* have is here and nothing else:

* ``entities.csv``    — what a memo becomes and how its ``@id`` is chosen
* ``properties.csv``  — which memo fields land where, via which named parser
* this file           — a ``PluginBase`` subclass with the two methods the
                        base can't guess: how to read your format
                        (``load_source``) and how to wrap the result
                        (``assemble``)

Classification, property mapping, ``@id`` resolution, and dedup all come from
the base defaults. ``golden.json`` + ``tests/test_example.py`` pin the output —
copy that pattern to test your own plugin without a reference converter.
Walkthrough: ``docs/NEW-PLUGIN.md``.
"""

from __future__ import annotations

from typing import Iterable

from ...core import Context, PluginBase, SourceRecord, records_from_items
from ...core.parsers import scalar, string_list


class ExamplePlugin(PluginBase):
    name = "example"
    # The names properties.csv references, mapped to shared parsers.
    import_parsers = {"scalar": scalar, "string_list": string_list}

    def load_source(self, source) -> Iterable[SourceRecord]:
        """The whole format-specific loading step: memos are a dict-of-lists."""
        return records_from_items({"memo": source["memos"]}, id_key="id")

    def assemble(self, ctx: Context) -> dict:
        return {"@graph": [ctx.out_nodes[i] for i in ctx.order]}


PLUGIN = ExamplePlugin()


def convert(direction: str, source: dict) -> dict:
    return PLUGIN.convert(direction, source)
