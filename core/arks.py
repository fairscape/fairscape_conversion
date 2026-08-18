"""Deterministic ARK minting — the fairscape identifier scheme, in core.

``ark:{naan}/{prefix}-{slug(name)}-{sha1(source)[:7]}``: the slug is the
readable half, the hash names the thing (a stable source string — a file path,
a rule name + outputs, a session id), so re-running a conversion over the same
source reproduces the same identifiers. This is the scheme nf-fairscape and
snakemake-report-plugin-fairscape mint, and the one the wrroc plugin composes
(with a ``wrroc-`` tag folded into the prefix).

Plugins that need a namespace tag put it in ``prefix`` (``wrroc-computation``);
the minter itself adds nothing.
"""

import hashlib
import re

DEFAULT_NAAN = "59853"


def slugify(text, max_len=40, fallback="entity"):
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug[:max_len].strip("-") or fallback


def short_hash(text, length=7):
    return hashlib.sha1(str(text).encode()).hexdigest()[:length]


def mint_ark(naan, prefix, name, source, fallback="entity"):
    return f"ark:{naan}/{prefix}-{slugify(name, fallback=fallback)}-{short_hash(source)}"
