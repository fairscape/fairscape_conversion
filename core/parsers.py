#!/usr/bin/env python3
"""Common property parsers any plugin can register.

Every parser speaks the one unified signature ``fn(value, rule, ctx)`` and
returns the parsed value or ``None`` for "set nothing". Register them in a
plugin's parser dicts under whatever name the CSV uses::

    import_parsers = {"scalar": core_parsers.scalar, "keep": core_parsers.identity}

This library is deliberately small: only behaviour that is genuinely the same
everywhere belongs here. A plugin whose "scalar" collapses lists its own way
(wrroc joins @id refs, d4d pipe-flattens) keeps its own parser — subtle
per-plugin differences must stay visible in the plugin, not hide behind a
shared name.
"""

from __future__ import annotations

_EMPTY = (None, "", [], {})


def drop(value, rule, ctx):
    """Always sets nothing — for documented one-way or ignored properties."""
    return None


def identity(value, rule, ctx):
    """The value unchanged, or nothing when it is empty."""
    return None if value in _EMPTY else value


def scalar(value, rule, ctx):
    """The value as a stripped string, or nothing when empty."""
    if value in _EMPTY:
        return None
    return str(value).strip() or None


def string_list(value, rule, ctx):
    """The value as a list of strings (a lone string becomes a 1-item list)."""
    if value in _EMPTY:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value if v not in _EMPTY] or None
    return [str(value)]


def constant(literal):
    """Factory: a parser that always sets ``literal`` (for synthesized fields)."""
    def _constant(value, rule, ctx):
        return literal
    return _constant
