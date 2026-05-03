#!/usr/bin/env python3
"""
backfill-registry.py — v2.5.2.1 Fix 2.

Closes CrossAI round 3 consensus finding (Codex + Claude major):
  Phase S registry catalogs only 24 of ~60 validators. `verify-validator-drift`
  can only surface drift on cataloged entries — ~36 legacy validators stay
  silently unobservable.

This script auto-discovers every `.claude/scripts/validators/*.py` (excluding
`_common.py`, `_i18n.py`, and the registry script itself), reads each
docstring first line, and appends a `registry.yaml` entry.

Behavior:
  - Idempotent: existing entries preserved; only NEW validators appended
  - Placeholder fields for uncatalogued: `added_in: pre-v2.5.2`,
    `severity: warn` (safe default), `domain: uncategorized` (force reviewer
    to classify), `runtime_target_ms: 5000` (generous), `phases_active: [all]`
  - Description from docstring first line (max 120 chars)
  - --dry-run prints what would be added without writing
  - --apply actually commits changes

Exit codes:
  0 = all validators catalogued (after apply) OR dry-run clean
  1 = drift detected + --dry-run (caller should re-run with --apply)
  2 = config / file error
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATORS_DIR = REPO_ROOT / ".claude" / "scripts" / "validators"
REGISTRY_PATH = VALIDATORS_DIR / "registry.yaml"

# Files to skip when scanning validators dir
SKIP_NAMES = {"_common.py", "_i18n.py", "registry.yaml", "backfill-registry.py"}


def _extract_docstring_first_line(py_path: Path) -> str | None:
    """Return the first non-empty line of the module docstring, or None."""
    try:
        text = py_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    # Find the first triple-quoted string
    m = re.search(r'^\s*"""(.*?)"""', text, re.DOTALL | re.MULTILINE)
    if not m:
        m = re.search(r"^\s*'''(.*?)'''", text, re.DOTALL | re.MULTILINE)
    if not m:
        return None

    body = m.group(1).strip()
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return None


def _file_to_id(py_path: Path) -> str:
    """Map file name → registry id by stripping common action prefixes."""
    stem = py_path.stem
    for prefix in ("verify-", "validate-", "evaluate-"):
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


def _load_registry_ids() -> set[str]:
    """Read registry.yaml and return the set of cataloged ids."""
    if not REGISTRY_PATH.exists():
        return set()
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    ids = set()
    for line in text.splitlines():
        m = re.match(r"\s*-\s*id:\s*(\S+)", line)
        if m:
            ids.add(m.group(1).strip().strip("'\""))
    return ids


def _discover_on_disk() -> list[Path]:
    return sorted(
        p for p in VALIDATORS_DIR.glob("*.py")
        if p.name not in SKIP_NAMES and not p.name.startswith("_")
    )


# v2.5.2.2: domain inference by filename substring (ordered — first match wins).
DOMAIN_RULES = [
    (("security", "auth", "jwt", "oauth", "2fa", "dast", "secret", "cve",
      "vuln", "cookie", "pkce", "hygiene", "container", "headers"),
     "security"),
    (("contract", "runtime-contract"), "contract"),
    (("crossai", "multi-cli", "consensus"), "crossai"),
    (("manifest", "artifact", "evidence", "freshness", "provenance"),
     "evidence"),
    (("lock", "journal", "orchestrator", "run-", "failure-state",
      "allow-flag"), "orchestrator"),
    (("bootstrap", "learn", "candidate", "reflect", "promotion",
      "carryforward"), "bootstrap"),
    (("test-requirements", "goal-coverage", "test-spec", "deferred-evidence",
      "not-scanned"), "test"),
    (("override-debt", "debt-sla", "debt-balance", "allow-flag-audit",
      "check-override"), "governance"),
    (("mutation", "wave", "build-telemetry", "build-crossai",
      "commit-attribution", "event-reconciliation",
      "acceptance-reconciliation"), "build"),
    (("i18n", "accessibility", "a11y", "visual", "ui-"), "frontend"),
    (("foundation", "project", "architecture", "scope", "pipeline"),
     "project"),
    (("drift", "registry", "codex-skill-mirror"), "meta"),
    # v2.5.2.3: goal-perf split out to dedicated performance domain
    # (Codex round-5 finding: security classification was a taxonomy miss).
    (("goal-perf", "perf-budget", "performance"), "performance"),
    (("goal-security", "input-validation"), "security"),
    (("validator-drift", "skill-runtime-contract"), "meta"),
    (("context-structure", "context-refs"), "context"),
    (("phase-exists", "plan-granularity"), "project"),
    (("review-skip-guard", "review-loop"), "review"),
    (("task-goal-binding", "test-first"), "test"),
    (("vg-design-coherence", "design-"), "frontend"),
]

# Severity inference by docstring keyword.
SEVERITY_RULES = [
    # keyword (any of) → severity
    (("BLOCK", "block_release", "forge", "CRITICAL", "MUST", "hard gate",
      "hard-block", "must have"), "block"),
    (("advisory", "informational", "WARN only", "warn-only", "observability"),
     "advisory"),
    (("WARN", "warning"), "warn"),
]


def _infer_domain(rid: str, description: str) -> str:
    """Return best-fit domain from filename substring + description."""
    text = f"{rid} {description}".lower()
    for substrings, domain in DOMAIN_RULES:
        for s in substrings:
            if s in text:
                return domain
    return "uncategorized"


def _infer_severity(description: str) -> str:
    """Return severity from description keywords."""
    for keywords, sev in SEVERITY_RULES:
        for k in keywords:
            if k in description:  # case-sensitive for BLOCK/MUST/CRITICAL
                return sev
    return "warn"


def _format_entry(rid: str, file_path: Path, description: str) -> str:
    """Build a YAML entry block for a validator."""
    rel = file_path.relative_to(REPO_ROOT).as_posix()
    desc_safe = description.replace("'", "''").strip()
    if not desc_safe:
        desc_safe = "TODO — legacy validator, docstring missing. Fill in."
    # v2.5.2.2: infer domain + severity from metadata (Codex round-4 finding
    # "36 placeholders all warn + uncategorized is partial closure").
    domain = _infer_domain(rid, description)
    severity = _infer_severity(description)
    return (
        f"\n  - id: {rid}\n"
        f"    path: {rel}\n"
        f"    severity: {severity}\n"
        f"    phases_active: [all]\n"
        f"    domain: {domain}\n"
        f"    runtime_target_ms: 5000\n"
        f"    added_in: pre-v2.5.2\n"
        f"    description: '{desc_safe}'\n"
    )


def _append_entries(new_blocks: list[str]) -> None:
    if not new_blocks:
        return
    existing = REGISTRY_PATH.read_text(encoding="utf-8")
    # Drop trailing pre-v2.5.2 comment block if present so new entries land
    # above it cleanly
    marker = "  # ──── Pre-v2.5.2 validators"
    if marker in existing:
        existing, tail = existing.split(marker, 1)
        existing = existing.rstrip() + "\n"
        # We replace the old comment block entirely — new entries
        # make the placeholder comment obsolete
    else:
        existing = existing.rstrip() + "\n"

    header = (
        "\n  # ──── Backfilled v2.5.2.1 (pre-v2.5.2 legacy validators) ────\n"
        "  # Entries below were auto-discovered + need per-entry review\n"
        "  # (domain, severity, phases_active may need tightening).\n"
    )
    payload = header + "".join(new_blocks)
    REGISTRY_PATH.write_text(existing + payload, encoding="utf-8")


def _reclassify_placeholders(apply: bool) -> tuple[int, list[dict]]:
    """v2.5.2.2: update existing `pre-v2.5.2 + uncategorized` entries with
    inferred domain + severity from filename substring + docstring keywords.
    Returns (count_updated, details)."""
    text = REGISTRY_PATH.read_text(encoding="utf-8")

    # Parse entries — split by "- id:" boundary
    chunks = re.split(r"(?=\n  - id:)", text)
    head = chunks[0]
    entries = chunks[1:]

    updates: list[dict] = []
    new_entries: list[str] = []
    for chunk in entries:
        # Extract fields from the chunk
        id_m = re.search(r"- id:\s*(\S+)", chunk)
        domain_m = re.search(r"domain:\s*(\S+)", chunk)
        severity_m = re.search(r"severity:\s*(\S+)", chunk)
        added_m = re.search(r"added_in:\s*(\S+)", chunk)
        desc_m = re.search(r"description:\s*'([^']*)'", chunk)

        if not id_m:
            new_entries.append(chunk)
            continue

        rid = id_m.group(1)
        current_domain = (domain_m.group(1) if domain_m else "").strip()
        current_severity = (severity_m.group(1) if severity_m else "").strip()
        added_in = (added_m.group(1) if added_m else "").strip()
        description = desc_m.group(1) if desc_m else ""

        # Only reclassify pre-v2.5.2 + uncategorized entries
        if added_in != "pre-v2.5.2" or current_domain != "uncategorized":
            new_entries.append(chunk)
            continue

        new_domain = _infer_domain(rid, description)
        new_severity = _infer_severity(description)

        if new_domain == current_domain and new_severity == current_severity:
            new_entries.append(chunk)
            continue

        updates.append({
            "id": rid,
            "domain_from": current_domain,
            "domain_to": new_domain,
            "severity_from": current_severity,
            "severity_to": new_severity,
        })

        # Rewrite only the domain + severity fields in this chunk
        updated_chunk = chunk
        if domain_m:
            updated_chunk = re.sub(
                r"(domain:\s*)\S+",
                lambda m: f"{m.group(1)}{new_domain}",
                updated_chunk, count=1,
            )
        if severity_m:
            updated_chunk = re.sub(
                r"(severity:\s*)\S+",
                lambda m: f"{m.group(1)}{new_severity}",
                updated_chunk, count=1,
            )
        new_entries.append(updated_chunk)

    if apply and updates:
        REGISTRY_PATH.write_text(head + "".join(new_entries), encoding="utf-8")

    return len(updates), updates


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="write changes to registry.yaml (default: dry-run)")
    ap.add_argument("--reclassify-placeholders", action="store_true",
                    help="v2.5.2.2: re-infer domain/severity for existing "
                         "pre-v2.5.2 + uncategorized entries")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.reclassify_placeholders:
        count, updates = _reclassify_placeholders(args.apply)
        if count == 0:
            if not args.quiet:
                print(f"✓ No pre-v2.5.2 uncategorized entries need reclassification")
            return 0
        icon = "✓" if args.apply else ""
        action = "reclassified" if args.apply else "would reclassify (dry-run)"
        print(f"{icon} {count} entries {action}:")
        for u in updates:
            print(f"  {u['id']}: domain {u['domain_from']!r}→{u['domain_to']!r}, "
                  f"severity {u['severity_from']!r}→{u['severity_to']!r}")
        return 0 if args.apply else 1

    if not REGISTRY_PATH.exists():
        print(f"\033[38;5;208mregistry.yaml not found at {REGISTRY_PATH}\033[0m",
              file=sys.stderr)
        return 2

    registered = _load_registry_ids()
    on_disk = _discover_on_disk()

    missing_entries = []
    for path in on_disk:
        rid = _file_to_id(path)
        if rid in registered:
            continue
        desc = _extract_docstring_first_line(path) or ""
        missing_entries.append((rid, path, desc))

    if not missing_entries:
        if not args.quiet:
            print(f"✓ All {len(on_disk)} validators cataloged in registry.yaml "
                  f"({len(registered)} existing entries)")
        return 0

    if args.apply:
        blocks = [_format_entry(rid, p, d) for rid, p, d in missing_entries]
        _append_entries(blocks)
        print(f"✓ Appended {len(missing_entries)} validator entries to "
              f"{REGISTRY_PATH.relative_to(REPO_ROOT)}")
        for rid, _p, d in missing_entries:
            print(f"  + {rid}: {d[:80]}")
        return 0

    # Dry-run
    print(f"\033[33mRegistry drift: {len(missing_entries)} validator(s) on disk \033[0m"
          f"but not cataloged.\n")
    for rid, p, d in missing_entries:
        print(f"  - {rid}")
        print(f"      path: {p.relative_to(REPO_ROOT).as_posix()}")
        print(f"      description: {d[:80] if d else '(no docstring)'}")
    print(f"\nRun with --apply to append placeholder entries.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
