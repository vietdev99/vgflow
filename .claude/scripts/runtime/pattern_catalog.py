"""D25 pattern catalog + selective web augmentation (RFC v9 PR-research-augment).

Test-strategy step needs edge-case patterns. Web search is expensive, slow,
non-deterministic. Pattern catalog is a curated local store of common
edge cases per surface kind (auth, payments, file upload, etc.) that the
strategy step queries first. Only on a catalog miss does it escalate to
WebSearch.

Catalog format (markdown frontmatter + body):
    ---
    id: payments-idempotency-collision
    surface: api
    tags: [payments, idempotency, retry]
    severity: high
    ---
    Pattern: Same Idempotency-Key with different body returns the cached
    response, not a 4xx — silent data corruption when caller retries with
    drift.

    Edge cases:
    - Caller A POST {amt: 100, key: K}; Caller B POST {amt: 200, key: K}
      → both see 100 receipt; B never billed.
    ...

API:
    catalog = load_catalog(catalog_dir)
    matches = match_patterns(catalog, surface="api", tags=["payments", "auth"])
    if not matches:
        # caller invokes WebSearch
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)$",
    re.DOTALL,
)


@dataclass
class Pattern:
    id: str
    surface: str
    tags: list[str] = field(default_factory=list)
    severity: str = "medium"
    body: str = ""
    path: Path | None = None


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Lightweight YAML-frontmatter parser (no full YAML dep needed for this format)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_lines = m.group("fm").splitlines()
    body = m.group("body").strip()
    out: dict = {}
    current_key: str | None = None
    for line in fm_lines:
        if not line.strip():
            continue
        if line.startswith("  - ") and current_key is not None:
            out.setdefault(current_key, []).append(line[4:].strip())
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        current_key = k
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1]
            out[k] = [t.strip() for t in inner.split(",") if t.strip()]
        elif v:
            out[k] = v
        else:
            out[k] = []  # awaiting bullet items
    return out, body


def load_pattern(path: Path) -> Pattern:
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    if "id" not in fm:
        raise ValueError(f"pattern at {path} missing id frontmatter")
    if "surface" not in fm:
        raise ValueError(f"pattern at {path} missing surface frontmatter")
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    return Pattern(
        id=str(fm["id"]),
        surface=str(fm["surface"]),
        tags=[str(t) for t in tags],
        severity=str(fm.get("severity", "medium")),
        body=body,
        path=path,
    )


def load_catalog(catalog_dir: Path) -> list[Pattern]:
    if not catalog_dir.exists():
        return []
    out: list[Pattern] = []
    for f in sorted(catalog_dir.glob("*.md")):
        try:
            out.append(load_pattern(f))
        except ValueError:
            continue  # skip malformed
    return out


def match_patterns(
    catalog: list[Pattern],
    *,
    surface: str | None = None,
    tags: Iterable[str] | None = None,
    require_all_tags: bool = False,
    severity_min: str | None = None,
) -> list[Pattern]:
    """Filter catalog by surface + tag overlap + severity floor."""
    sev_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    floor = sev_rank.get(severity_min or "", 0)
    tags_set = set(tags or [])

    out: list[Pattern] = []
    for p in catalog:
        if surface and p.surface != surface:
            continue
        if tags_set:
            p_tags = set(p.tags)
            if require_all_tags:
                if not tags_set.issubset(p_tags):
                    continue
            else:
                if not (tags_set & p_tags):
                    continue
        if floor and sev_rank.get(p.severity, 2) < floor:
            continue
        out.append(p)
    # Sort: high severity first, then by id for determinism
    out.sort(key=lambda p: (-sev_rank.get(p.severity, 2), p.id))
    return out


def needs_web_augment(
    matches: list[Pattern],
    *,
    min_matches: int = 2,
) -> bool:
    """Caller signal: catalog hit insufficient → escalate to WebSearch."""
    return len(matches) < min_matches
