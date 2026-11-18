"""Module lifecycle rules, from the catalog-number list in lifecycle.json.

The list is SEED data compiled from public Rockwell discontinuation notices; its
_meta block says when. Check it against Rockwell's Product Compatibility and
Download Center before buying anything. Edit the JSON to add or correct entries.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from lint.context import Context, Finding
from lint.registry import check

_PATH = Path(__file__).with_name("lifecycle.json")
_CODE = {"Discontinued": "ERR017", "End of Life": "WAR021", "Active Mature": "INF009"}


@lru_cache(maxsize=1)
def dataset() -> tuple[dict, dict]:
    """(entries by upper-case catalog, meta)."""
    try:
        raw = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    meta = raw.pop("_meta", {})
    return {k.upper(): v for k, v in raw.items()}, meta


@check("ERR017", "WAR021", "INF009")
def lifecycle(ctx: Context) -> list[Finding]:
    entries, meta = dataset()
    out, seen = [], set()
    for m in ctx.project.modules:
        cat = m.catalog.upper()
        if not cat or cat in seen or cat not in entries:
            continue
        seen.add(cat)
        e = entries[cat]
        code = _CODE.get(e.get("status", ""))
        if not code:
            continue
        repl = f" Suggested replacement: {e['replacement']}." if e.get("replacement") else ""
        when = f" ({e['eol_date']})" if e.get("eol_date") else ""
        status = e["status"].lower()
        out.append(Finding(code, f"Module '{m.name}' is a {m.catalog}, which is {status}{when}.{repl}",
                           f"Module:{m.name}", f"Lifecycle list dated {meta.get('scraped_at', '?')}; verify on Rockwell PCDC."))
    return out
