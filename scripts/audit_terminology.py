#!/usr/bin/env python3
"""Audit user-facing content for prohibited development terminology.

Prohibited (case-insensitive, any separator, common inflections): demo, synthetic, prototype, mock data, dummy data,
AI-generated demo, vibecoded.

What is scanned (everything a user can read, directly or through the API):
  * React sources and index.html (visible text, tooltips, aria-labels, page titles, notifications, validation messages)
  * every backend module (route docstrings become OpenAPI text; response and error strings)
  * db/seed.sql (location names, labels and other values that appear in the interface)
  * ml/reports/*.json and ml/artifacts/*/metadata.json (served through /api/ml/*)
  * iot-simulator/ (console output), frontend/nginx.conf (error pages)
  * optionally the production bundle (--dist), where JavaScript's own `prototype` keyword is not text and is ignored

NOT scanned, deliberately: tests, technical documentation (README, ml/*.md, docs/), scripts and third-party licences, where the terms may be
needed to describe the data accurately. This tool never rewrites anything: every match is reviewed by a person. Exceptions must be written
down with a reason in scripts/terminology_allowlist.json.

    python scripts/audit_terminology.py            # exit 1 when any match exists
    python scripts/audit_terminology.py --json
    python scripts/audit_terminology.py --dist     # also scan frontend/dist (after `npm run build`)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEP = r"[\s_\-\u2010-\u2015./]*"
PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"ai" + SEP + r"generated" + SEP + r"demo\w*|"
    r"demos?|demoed|demoing|"
    r"synthetic(?:ally)?|"
    r"prototypes?|prototyped|prototyping|"
    r"mock(?:ed)?" + SEP + r"data(?:sets?)?|"
    r"dummy" + SEP + r"data(?:sets?)?|"
    r"vibe" + SEP + r"cod(?:ed|ing|er)"
    r")(?![A-Za-z0-9])", re.I)
INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
SCOPE = [("frontend/src", {".ts", ".tsx", ".css", ".html"}), ("frontend/index.html", {".html"}), ("backend/app", {".py"}),
         ("db/seed.sql", {".sql"}), ("ml/reports", {".json"}), ("ml/artifacts", {".json"}), ("iot-simulator", {".py"}), ("frontend/nginx.conf.template", {".template"}), ("frontend/public", {".js"})]
DIST = ("frontend/dist", {".js", ".html", ".css"})
SKIP_PARTS = {"node_modules", "__pycache__", "dist"}
ALLOWLIST_FILE = ROOT / "scripts" / "terminology_allowlist.json"


def normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(INVISIBLE)


def is_code_keyword(line: str, m: re.Match) -> bool:
    """JavaScript/TypeScript `prototype` property access (Object.prototype, Foo.prototype.bar) is code, not wording."""
    if m.group(0).lower() != "prototype":
        return False
    before, after = line[:m.start()], line[m.end():]
    if before[-1:] in ("'", '"', "`") and after[:1] in ("'", '"', "`"):
        return True                       # the quoted property name, e.g. Object.defineProperty(e, "prototype", ...)
    return before.endswith(".") or after.startswith((".", "=", " =", "[", ")", ",", ";", "}", "||", " ||", " &&", "&&", ":", " :"))


def find(text: str, *, code: bool = True) -> list[tuple[int, re.Match, str]]:
    out = []
    for n, raw in enumerate(normalise(text).splitlines(), 1):
        for m in PATTERN.finditer(raw):
            if code and is_code_keyword(raw, m):
                continue
            out.append((n, m, raw))
    return out


def allowlist() -> list[dict]:
    try:
        return json.loads(ALLOWLIST_FILE.read_text(encoding="utf-8")).get("allowed", [])
    except (OSError, ValueError):
        return []


def files(include_dist: bool = False):
    scope = SCOPE + ([DIST] if include_dist else [])
    for rel, exts in scope:
        p = ROOT / rel
        if p.is_file():
            yield p
        elif p.is_dir():
            yield from sorted(f for f in p.rglob("*") if f.is_file() and f.suffix in exts and not (SKIP_PARTS & set(f.relative_to(ROOT).parts) - ({"dist"} if include_dist and rel == DIST[0] else set())))


def scan(include_dist: bool = False) -> list[dict]:
    allowed = allowlist()
    hits = []
    for f in files(include_dist):
        rel = str(f.relative_to(ROOT))
        for n, m, raw in find(f.read_text(encoding="utf-8", errors="replace"), code=f.suffix in {".ts", ".tsx", ".js"}):
            if any(a.get("file") == rel and a.get("match", "").lower() == m.group(0).lower() and a.get("reason") for a in allowed):
                continue
            hits.append({"file": rel, "line": n, "match": m.group(0), "text": raw.strip()[:160]})
    return hits


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dist", action="store_true", help="also scan frontend/dist")
    a = ap.parse_args()
    h = scan(a.dist)
    n_files = sum(1 for _ in files(a.dist))
    if a.json:
        print(json.dumps(h, indent=2))
    else:
        for x in h:
            print(f"{x['file']}:{x['line']}: [{x['match']}] {x['text']}")
        print(f"{len(h)} match(es) in {n_files} files scanned")
    sys.exit(1 if h else 0)
