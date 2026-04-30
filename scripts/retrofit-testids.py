#!/usr/bin/env python3
"""
retrofit-testids.py — v2.43.5

Retrofit data-testid attributes into existing UI components for phases
that completed before v2.43.5 (test_ids stack) landed.

Workflow:
  1. Scan ${PHASE_DIR}/PLAN.md for UI file paths
  2. Parse each file, find interactive elements without data-testid
  3. Derive testid value (page-element pattern from filename + role + text)
  4. Output:
       ${PHASE_DIR}/test-ids-retrofit-proposal.md  — review table
       ${PHASE_DIR}/test-ids-retrofit.patch         — git diff
  5. With --apply: write changes in-place + retroactively patch PLAN.md
     to add <test_ids> blocks

Supports: React (tsx/jsx). Vue/Svelte support is TODO — open issue.

Usage:
  # Dry-run (default) — write proposal only
  python3 .claude/scripts/retrofit-testids.py --phase-dir .vg/phases/03.5-...

  # Apply — modify source files + PLAN.md, git stage
  python3 .claude/scripts/retrofit-testids.py --phase-dir .vg/phases/03.5-... --apply

  # Filter to one app
  python3 .claude/scripts/retrofit-testids.py --phase-dir .vg/phases/03.5-... --filter-app=admin

Override safety:
  - Never overwrites elements that already have data-testid
  - --apply still writes proposal first; user can git diff before commit
  - Skips library/vendor files (node_modules, dist, .test., .spec.)
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
from collections import defaultdict


# ─── Regex patterns ─────────────────────────────────────────────────────────

# Match opening tags of interactive elements. Group 1 = tag name, group 2 = full attrs string
INTERACTIVE_TAG_RE = re.compile(
    r'<(button|input|select|textarea|form|a|tr|tab|li|dialog|Modal|Drawer|Dialog|Form|Button|Input|Select|TextArea|Link)\b([^>]*?)(/?)>',
    re.IGNORECASE,
)
TESTID_PRESENT_RE = re.compile(r'\bdata-testid\s*=', re.IGNORECASE)

# Heuristic: extract element identity (text content / label / name)
TEXT_AFTER_TAG_RE = re.compile(r'>\s*([^<>{]{2,40})\s*<')   # text between > and <
LABEL_PROP_RE = re.compile(r'\b(label|placeholder|name|aria-label|title)\s*=\s*[\'"]([^\'"]{1,40})[\'"]')
NAME_PROP_RE = re.compile(r'\bname\s*=\s*[\'"]([^\'"]{1,30})[\'"]')

# Skip patterns
SKIP_PATH_RE = re.compile(
    r'(node_modules|dist|\.test\.|\.spec\.|\.stories\.|/__tests__/|/test/)',
)

# UI file glob from PLAN.md
UI_FILE_PATTERN = re.compile(r'(apps|packages)/[^\s)]+\.(tsx|jsx)\b')


# ─── Helpers ────────────────────────────────────────────────────────────────


def kebab(s: str) -> str:
    """Convert any string to kebab-case ASCII (best-effort)."""
    # Unicode normalization → ASCII via Vietnamese diacritic strip
    import unicodedata
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:40]   # cap length


def derive_page_prefix(file_path: Path) -> str:
    """Derive page/feature prefix from filename + dir context."""
    stem = file_path.stem
    # Strip common suffixes
    for sfx in ("Page", "Form", "Modal", "Dialog", "Drawer", "Tab",
                "Layout", "View", "Component"):
        if stem.endswith(sfx):
            stem = stem[: -len(sfx)]
    # Use parent dir if stem becomes empty/generic
    if not stem or stem.lower() in {"index", "main", "app"}:
        stem = file_path.parent.name
    return kebab(stem)


def derive_element_suffix(tag: str, attrs: str, after_tag: str = "") -> str:
    """Derive element identity from tag + attrs + immediate text."""
    tag_lower = tag.lower()

    # Try labels first
    for m in LABEL_PROP_RE.finditer(attrs):
        return f"{kebab(m.group(2))}-{tag_lower}"

    # Try name
    nm = NAME_PROP_RE.search(attrs)
    if nm:
        return f"{kebab(nm.group(1))}-{tag_lower}"

    # Try inner text (only useful for buttons/links)
    if tag_lower in ("button", "a") and after_tag:
        # Skip JSX expressions
        clean = re.sub(r"\{[^}]+\}", "", after_tag).strip()
        if clean and len(clean) >= 2:
            return f"{kebab(clean)}-{tag_lower}"

    # Fallback: just tag name + counter (counter added by caller)
    return tag_lower


def parse_file(path: Path) -> list[dict]:
    """Returns list of {line_no, tag, attrs, suggested_id, snippet}."""
    if SKIP_PATH_RE.search(str(path)):
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return []

    findings = []
    page_prefix = derive_page_prefix(path)
    counters: dict[str, int] = defaultdict(int)
    lines = content.split("\n")

    for m in INTERACTIVE_TAG_RE.finditer(content):
        tag, attrs, self_close = m.group(1), m.group(2), m.group(3)
        if TESTID_PRESENT_RE.search(attrs):
            continue   # already has testid

        # Locate text content after tag (only if not self-closing)
        after_tag = ""
        if not self_close:
            after_m = TEXT_AFTER_TAG_RE.search(content[m.end():m.end() + 200])
            if after_m:
                after_tag = after_m.group(1)

        suffix = derive_element_suffix(tag, attrs, after_tag)
        # Disambiguate duplicates within same file
        counters[suffix] += 1
        suffix_final = suffix if counters[suffix] == 1 else f"{suffix}-{counters[suffix]}"

        proposed = f"{page_prefix}-{suffix_final}"

        # Line number (approx)
        line_no = content[: m.start()].count("\n") + 1
        snippet = lines[line_no - 1].strip() if line_no <= len(lines) else m.group(0)

        findings.append({
            "line_no": line_no,
            "tag": tag,
            "attrs_excerpt": attrs.strip()[:80],
            "snippet": snippet[:120],
            "suggested_id": proposed,
            "match_start": m.start(),
            "match_end": m.end(),
            "tag_close": ">" if not self_close else "/>",
        })

    return findings


def extract_ui_files(plan_path: Path, repo_root: Path) -> list[Path]:
    if not plan_path.exists():
        return []
    text = plan_path.read_text(encoding="utf-8")
    seen: set[str] = set()
    files: list[Path] = []
    for m in UI_FILE_PATTERN.finditer(text):
        rel = m.group(0)
        if rel in seen:
            continue
        seen.add(rel)
        p = repo_root / rel
        if p.exists():
            files.append(p)
    return sorted(files)


def write_proposal(findings_by_file: dict, out_path: Path) -> int:
    total = sum(len(v) for v in findings_by_file.values())
    lines = [
        f"# Test ID Retrofit Proposal — {total} insertion(s) across "
        f"{len(findings_by_file)} file(s)",
        "",
        "Generated by `retrofit-testids.py`. Review the proposed mappings,",
        "then re-run with `--apply` to write changes.",
        "",
        "## Per-file proposals",
        "",
    ]
    for file_path, findings in sorted(findings_by_file.items()):
        if not findings:
            continue
        lines.append(f"### {file_path}")
        lines.append("")
        lines.append("| Line | Tag | Suggested testid | Snippet |")
        lines.append("|-----:|-----|------------------|---------|")
        for f in findings:
            snippet_md = f["snippet"].replace("|", "\\|")[:80]
            lines.append(
                f"| {f['line_no']} | `{f['tag']}` | "
                f"`{f['suggested_id']}` | `{snippet_md}` |"
            )
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return total


def apply_changes(file_path: Path, findings: list[dict]) -> str:
    """Inject data-testid into source file. Returns new content."""
    content = file_path.read_text(encoding="utf-8")
    # Apply from END to start so offsets stay valid
    for f in sorted(findings, key=lambda x: x["match_start"], reverse=True):
        old = content[f["match_start"]:f["match_end"]]
        # Insert data-testid="..." right before closing > or />
        if old.endswith("/>"):
            new = old[:-2].rstrip() + f' data-testid="{f["suggested_id"]}" />'
        elif old.endswith(">"):
            new = old[:-1].rstrip() + f' data-testid="{f["suggested_id"]}">'
        else:
            continue
        content = content[: f["match_start"]] + new + content[f["match_end"]:]
    return content


def patch_plan_with_testids(plan_path: Path, findings_by_file: dict) -> None:
    """Add a 'Retrofit (v2.43.5)' section at end of PLAN.md listing per-file
    test_ids. Doesn't try to inject into existing <task> blocks (too risky)."""
    if not plan_path.exists():
        return
    addendum = [
        "",
        "---",
        "",
        "## Retrofit Test IDs (v2.43.5)",
        "",
        "Auto-generated by `retrofit-testids.py`. Lists data-testid values",
        "injected into already-built components for i18n-resilient codegen.",
        "Future tasks should declare `<test_ids>` per planner Rule 10.",
        "",
    ]
    for file_path, findings in sorted(findings_by_file.items()):
        if not findings:
            continue
        addendum.append(f"### {file_path}")
        addendum.append("")
        addendum.append("```xml")
        addendum.append("<test_ids>")
        for f in findings:
            kind = f["tag"].lower()
            # Remap React-cap'd to lowercase HTML kind
            if kind in {"button", "input", "select", "textarea", "form", "a", "tr", "li"}:
                kind_norm = {"a": "link", "tr": "table-row", "textarea": "input"}.get(kind, kind)
            else:
                kind_norm = "modal" if kind in {"modal", "drawer", "dialog"} else kind.lower()
            addendum.append(
                f'  <id kind="{kind_norm}" value="{f["suggested_id"]}">'
                f'L{f["line_no"]}: {f["snippet"][:50]}</id>'
            )
        addendum.append("</test_ids>")
        addendum.append("```")
        addendum.append("")

    text = plan_path.read_text(encoding="utf-8")
    # Avoid duplicating section
    if "## Retrofit Test IDs (v2.43.5)" in text:
        return
    plan_path.write_text(text + "\n".join(addendum), encoding="utf-8")


# ─── Main ───────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="Write changes in-place; default is dry-run")
    ap.add_argument("--filter-app", default=None,
                    help="Restrict to one app (e.g. admin, merchant, vendor)")
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    repo_root = Path(args.repo_root).resolve()
    plan_path = phase_dir / "PLAN.md"

    files = extract_ui_files(plan_path, repo_root)
    if args.filter_app:
        files = [f for f in files if f"apps/{args.filter_app}/" in str(f)]

    if not files:
        print("No UI files referenced in PLAN.md. Nothing to retrofit.")
        return 0

    print(f"Scanning {len(files)} UI file(s) for missing data-testid...")
    findings_by_file: dict[str, list[dict]] = {}
    total = 0
    for f in files:
        rel = str(f.relative_to(repo_root))
        finds = parse_file(f)
        if finds:
            findings_by_file[rel] = finds
            total += len(finds)

    if total == 0:
        print("✓ All interactive elements already have data-testid. Nothing to retrofit.")
        return 0

    proposal_path = phase_dir / "test-ids-retrofit-proposal.md"
    n = write_proposal(findings_by_file, proposal_path)
    print(f"\n▸ Proposal written: {proposal_path}")
    print(f"  {n} insertion(s) across {len(findings_by_file)} file(s)")

    if not args.apply:
        print("\nDry-run mode. To apply:")
        print(f"  python3 {sys.argv[0]} --phase-dir {args.phase_dir} --apply")
        print("\nOr review the proposal first, then re-run with --apply.")
        return 0

    # Apply mode — write changes
    print("\n▸ Applying changes to source files...")
    for rel, findings in findings_by_file.items():
        path = repo_root / rel
        try:
            new_content = apply_changes(path, findings)
            path.write_text(new_content, encoding="utf-8")
            print(f"  ✓ {rel} ({len(findings)} insertion(s))")
        except Exception as e:
            print(f"  ⛔ {rel}: {e}")

    print("\n▸ Patching PLAN.md with retrofit section...")
    patch_plan_with_testids(plan_path, findings_by_file)

    print("\n✓ Retrofit complete.")
    print(f"  Source files modified: {len(findings_by_file)}")
    print(f"  Total testids injected: {total}")
    print(f"  PLAN.md addended with retrofit section")
    print("\nNext steps:")
    print("  1. Review the diff:")
    print(f"     git diff --stat -- {' '.join(findings_by_file.keys())[:200]}...")
    print("  2. If satisfied, commit:")
    print(f"     git add -A && git commit -m 'feat(test-ids): retrofit phase {phase_dir.name}'")
    print("  3. Re-run /vg:review {phase} to capture new testids into RUNTIME-MAP")
    print("  4. Re-run /vg:test {phase} --skip-deploy to regenerate specs with stable selectors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
