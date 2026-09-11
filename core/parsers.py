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

import mimetypes
import os

_EMPTY = (None, "", [], {})

# Extensions Python's mimetypes table gets wrong or does not know. It is a
# desktop-file table: '.vcf' there is a vCard address book, not the Variant
# Call Format a genomics pipeline writes, and the formats below are absent
# altogether. Guessing wrong is worse than not guessing, because a data loader
# reads encodingFormat to decide how to parse the file.
MIME_OVERRIDES = {
    "bam": "application/x-bam",
    "bai": "application/octet-stream",
    "bed": "text/x-bed",
    "cram": "application/x-cram",
    "crai": "application/octet-stream",
    "fa": "text/x-fasta",
    "fasta": "text/x-fasta",
    "fna": "text/x-fasta",
    "fastq": "text/x-fastq",
    "fq": "text/x-fastq",
    "gff": "text/x-gff3",
    "gff3": "text/x-gff3",
    "gtf": "text/x-gtf",
    "h5": "application/x-hdf5",
    "hdf5": "application/x-hdf5",
    "parquet": "application/vnd.apache.parquet",
    "sam": "text/x-sam",
    "vcf": "text/x-vcf",
    "yaml": "application/yaml",
    "yml": "application/yaml",
}


def encoding_format_of(path):
    """A MIME type for a file path — the value that lands in Dataset.format.

    Overrides first (see MIME_OVERRIDES), then the standard table, then the
    bare extension so the crate still says something.
    """
    ext = os.path.splitext(str(path))[1].lstrip(".").lower()
    if ext in MIME_OVERRIDES:
        return MIME_OVERRIDES[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or ext or "unknown"


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
