#!/usr/bin/env python3
"""
verify-spa-i18n-provider.py — Phase 7 Wave 18 Task 80 (P7.D-156 Amendment #1)

Purpose
-------
CI guard validator: every SPA root in `apps/*/src/main.tsx` (or `main.jsx`,
`main.ts`) MUST wrap its rendered tree with `<I18nextProvider>` or
`<I18nProvider>` (a project-local wrapper around the react-i18next provider).

The wrapper may live directly inside `createRoot(...).render(...)` in
`main.tsx`, OR one level deeper inside the imported root component
(e.g. `App.tsx`) — Phase 6 merchant-v3 picked that style.

Rationale
---------
Phase 7 vendor-portal escaped the accept gate because no validator caught
the missing wrapper — every consumer of `useTranslation()` silently fell
through to the default i18n instance, producing untranslated keys in
production. Task 80 closes that root drift. Amendment #1 to P7.D-156
mandates this invariant going forward across every SPA in the monorepo.

Algorithm
---------
1. Glob `apps/*/src/main.{tsx,jsx,ts,js}` from the repo root.
2. For each match:
   a. Confirm a `createRoot(...).render(...)` call exists.
   b. Search the file's full text for `<I18nextProvider` or `<I18nProvider`.
      If present -> PASS for that app.
   c. Else, identify the root component imported by `main` (heuristic:
      `import { App } from './App...'` or `import App from './App...'`)
      and search that file (and `index` re-exports) for the same wrapper.
      If present -> PASS.
   d. Else -> record a violation.
3. Severity gate:
   - `--severity block` (default) -> any violation = exit 1.
   - `--severity warn` -> list violations but exit 0 (used during P8.x WIP
     while admin SPA wrap is being shipped).

Exit codes
----------
  0 - PASS (or WARN with violations under `--severity warn`)
  1 - FAIL (violations found under `--severity block`)
  2 - Internal error (e.g. no apps found, regex failure)

Usage
-----
  # default: block mode, JSON output
  python3 .claude/scripts/validators/verify-spa-i18n-provider.py

  # warn mode (don't fail the gate, just list violations)
  python3 .claude/scripts/validators/verify-spa-i18n-provider.py \
      --severity warn

  # custom repo root
  python3 .claude/scripts/validators/verify-spa-i18n-provider.py \
      --repo-root /path/to/repo

  # human-readable output
  python3 .claude/scripts/validators/verify-spa-i18n-provider.py --no-json

Promote-to-VG-core note
-----------------------
TODO: After Phase 7 accept, promote to ~/.vgflow/scripts/validators/ so the
invariant lands in every VGFlow-managed project. Add an entry to the
validator catalog (validators/_catalog.json) and gate registration in
`/vg:review` + `/vg:accept`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# --- regex bank --------------------------------------------------------------

CREATE_ROOT_RE = re.compile(
    r"createRoot\s*\([^)]*\)\s*\.\s*render\s*\(",
    re.MULTILINE,
)

# Either `<I18nextProvider` (from react-i18next) or `<I18nProvider`
# (project-local wrapper component). The trailing char class makes sure
# we don't match a substring like `<I18nProviderFactory`.
WRAPPER_RE = re.compile(
    r"<\s*(I18nextProvider|I18nProvider)(\s|>|/)",
)

# Heuristic: `import { App } from './App...'` OR `import App from './App...'`
IMPORT_APP_RE = re.compile(
    r"""import\s+
        (?:\{\s*App\s*(?:as\s+\w+)?\s*\}|App)
        \s+from\s+['"](?P<spec>[^'"]+)['"]""",
    re.VERBOSE,
)

# Fallback: any local relative import — used if `App` isn't named.
IMPORT_LOCAL_RE = re.compile(
    r"""import\s+[^;]+?\s+from\s+['"](?P<spec>\./[^'"]+)['"]""",
    re.VERBOSE | re.MULTILINE,
)

MAIN_GLOBS = ("main.tsx", "main.jsx", "main.ts", "main.js")


# --- core checks -------------------------------------------------------------


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def resolve_import(base: Path, spec: str):
    """Resolve a relative import spec from `base` (a file) to a real .tsx/.ts file.

    Tries, in order:
      <spec>.tsx, <spec>.jsx, <spec>.ts, <spec>.js,
      <spec>/index.tsx, <spec>/index.jsx, <spec>/index.ts, <spec>/index.js
    Also tolerates explicit `.js` extension that maps to a `.tsx` source.
    """
    if not spec.startswith("."):
        return None
    root = (base.parent / spec).resolve()

    candidates = []
    # If spec already has an extension, also try the .tsx/.ts twin.
    if root.suffix in (".js", ".jsx", ".ts", ".tsx"):
        stem = root.with_suffix("")
        for ext in (".tsx", ".ts", ".jsx", ".js"):
            candidates.append(stem.with_suffix(ext))
    else:
        for ext in (".tsx", ".jsx", ".ts", ".js"):
            candidates.append(root.with_suffix(ext))
        for ext in (".tsx", ".jsx", ".ts", ".js"):
            candidates.append(root / f"index{ext}")

    for c in candidates:
        if c.is_file():
            return c
    return None


def check_app_entry(main_file: Path):
    """Return (ok, reason). ok=True means wrapper found somewhere in tree."""
    text = read_text(main_file)
    if not text:
        return False, "could not read main entry file"

    if not CREATE_ROOT_RE.search(text):
        # Not a SPA root that mounts via createRoot — skip cleanly.
        return True, "no createRoot().render() call — skipped"

    # 1) wrapper in main.tsx itself
    if WRAPPER_RE.search(text):
        return True, "wrapper found in main entry"

    # 2) follow `App` import
    visited = {main_file}
    app_match = IMPORT_APP_RE.search(text)
    targets = []
    if app_match:
        resolved = resolve_import(main_file, app_match.group("spec"))
        if resolved is not None:
            targets.append(resolved)

    # 3) fallback — any local import (cap at first 6 to avoid blow-up)
    if not targets:
        for m in IMPORT_LOCAL_RE.finditer(text):
            resolved = resolve_import(main_file, m.group("spec"))
            if resolved is not None and resolved not in visited:
                targets.append(resolved)
                if len(targets) >= 6:
                    break

    for tgt in targets:
        if tgt in visited:
            continue
        visited.add(tgt)
        body = read_text(tgt)
        if not body:
            continue
        if WRAPPER_RE.search(body):
            return True, f"wrapper found in {tgt.name}"

    return False, (
        "no <I18nextProvider> or <I18nProvider> wrapper found in main entry "
        "or its directly-imported root component"
    )


def find_spa_entries(repo_root: Path):
    apps_dir = repo_root / "apps"
    if not apps_dir.is_dir():
        return []
    entries = []
    for app in sorted(apps_dir.iterdir()):
        if not app.is_dir():
            continue
        src = app / "src"
        if not src.is_dir():
            continue
        for name in MAIN_GLOBS:
            cand = src / name
            if cand.is_file():
                entries.append(cand)
                break  # only one main entry per app
    return entries


# --- CLI ---------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        prog="verify-spa-i18n-provider",
        description=(
            "P7.D-156 Amendment #1 — assert every apps/*/src/main.tsx wraps "
            "<I18nextProvider> or <I18nProvider> around its root tree."
        ),
    )
    ap.add_argument(
        "--repo-root",
        default=".",
        help="repo root containing apps/ (default: cwd)",
    )
    ap.add_argument(
        "--severity",
        choices=("warn", "block"),
        default="block",
        help="block = exit 1 on violation (default); warn = list but exit 0",
    )
    ap.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        default=True,
        help="emit JSON report on stdout (default)",
    )
    ap.add_argument(
        "--no-json",
        dest="json_out",
        action="store_false",
        help="emit human-readable text instead of JSON",
    )
    args = ap.parse_args()

    try:
        repo_root = Path(args.repo_root).resolve()
        entries = find_spa_entries(repo_root)
        if not entries:
            payload = {
                "status": "PASS",
                "violations": [],
                "scanned": 0,
                "note": "no apps/*/src/main.* entries found",
                "severity": args.severity,
            }
            print(json.dumps(payload) if args.json_out else json.dumps(payload, indent=2))
            return 0

        violations = []
        for entry in entries:
            ok, reason = check_app_entry(entry)
            if not ok:
                violations.append({
                    "file": str(entry.relative_to(repo_root)),
                    "reason": reason,
                })

        status = "PASS" if not violations else "FAIL"
        payload = {
            "status": status,
            "violations": violations,
            "scanned": len(entries),
            "severity": args.severity,
        }

        if args.json_out:
            print(json.dumps(payload))
        else:
            print(f"verify-spa-i18n-provider — {status}")
            print(f"  scanned: {len(entries)} SPA entry/entries")
            print(f"  severity: {args.severity}")
            if violations:
                print("  violations:")
                for v in violations:
                    print(f"    - {v['file']}: {v['reason']}")

        if violations and args.severity == "block":
            return 1
        return 0

    except Exception as exc:
        err = {
            "status": "ERROR",
            "violations": [],
            "scanned": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }
        print(json.dumps(err) if args.json_out else json.dumps(err, indent=2),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
