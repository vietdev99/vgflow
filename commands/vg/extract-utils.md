---
name: vg:extract-utils
description: One-shot migration — move duplicate helpers into canonical @vollxssp/utils package + rewrite imports
argument-hint: "[--scan | --extract NAME | --interactive | --threshold N]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
---

<rules>
1. **VG-native** — no GSD delegation. Self-contained.
2. **Config-driven** — reads canonical package name from `PROJECT.md` → `## Shared Utility Contract` table (first column = name, second column = `module.ts`).
3. **Atomic per helper** — each helper extraction is ONE commit. Failure reverts that helper only.
4. **Read-only in `--scan` mode** — default shows candidates, doesn't modify code.
5. **Typecheck gate** — after each extraction, `pnpm turbo typecheck --filter <affected>` must pass. Fail → revert commit.
6. **Layer 1 companion** — complements Layer 2+3 (scope gate + blueprint gate + build gate) that PREVENT new duplicates. This is the one-shot RECOVERY for existing duplicates.
</rules>

<objective>
Migrate duplicate helper declarations from scattered files into the canonical `packages/utils/src/` package, rewriting all imports. Root cause of tsc OOM + graphify god-node noise.

Modes:
- `--scan` (default) — just show ranked candidates, no writes
- `--extract <name>` — extract one helper (e.g. `formatCurrency`)
- `--interactive` — scan + user picks which to extract
- `--threshold N` — only propose helpers with ≥N copies (default 3)
- `--all` — extract every helper above threshold

Pipeline position: anytime after `/vg:project` establishes contract. Run once, then Layer 2+3 prevents regression.
</objective>

<process>

**Config:** Read `.claude/commands/vg/_shared/config-loader.md` first.

<step name="0_validate">
Validate prerequisites:

```bash
# Contract must exist (from /vg:project — PROJECT.md Shared Utility Contract section)
PROJECT_MD="${PLANNING_DIR}/PROJECT.md"
if [ ! -f "$PROJECT_MD" ]; then
  echo "⛔ PROJECT.md missing. Run /vg:project --init-only first to establish utility contract."
  exit 1
fi
if ! grep -q "^## Shared Utility Contract" "$PROJECT_MD"; then
  echo "⛔ PROJECT.md has no Shared Utility Contract section."
  echo "   Add the section per vg.config.md template, then re-run."
  exit 1
fi

# Canonical package path must exist
CANONICAL_PKG=$(grep -oE "\`@[^/]+/utils\`" "$PROJECT_MD" | head -1 | tr -d '`')
if [ -z "$CANONICAL_PKG" ]; then
  echo "⛔ Cannot determine canonical package from PROJECT.md"
  exit 1
fi

# Derive short name (e.g., @vollxssp/utils → utils)
PKG_SHORT="${CANONICAL_PKG##*/}"
CANONICAL_DIR="packages/${PKG_SHORT}"
if [ ! -d "${CANONICAL_DIR}/src" ]; then
  echo "⛔ ${CANONICAL_DIR}/src does not exist."
  echo "   Create the package scaffold first, or fix the path in PROJECT.md."
  exit 1
fi
INDEX_TS="${CANONICAL_DIR}/src/index.ts"
[ ! -f "$INDEX_TS" ] && touch "$INDEX_TS"

echo "✓ Canonical package: ${CANONICAL_PKG} at ${CANONICAL_DIR}/src/"
```
</step>

<step name="1_parse_args">
Parse `${ARGUMENTS}`:
- First non-flag token → mode (`--scan` default)
- `--extract <name>` → single-helper mode
- `--interactive` → scan + prompt
- `--all` → batch
- `--threshold N` → min copies (default 3)

```bash
MODE="scan"
HELPER_NAME=""
THRESHOLD="${THRESHOLD:-3}"

for arg in ${ARGUMENTS}; do
  case "$arg" in
    --scan)          MODE="scan" ;;
    --extract)       MODE="extract-one" ;;
    --interactive)   MODE="interactive" ;;
    --all)           MODE="all" ;;
    --threshold=*)   THRESHOLD="${arg#--threshold=}" ;;
    -*)              ;;  # unknown flag, skip
    *)
      if [ "$MODE" = "extract-one" ] && [ -z "$HELPER_NAME" ]; then
        HELPER_NAME="$arg"
      fi
      ;;
  esac
done

echo "Mode: $MODE | Threshold: $THRESHOLD | Helper: ${HELPER_NAME:-<any>}"
```
</step>

<step name="2_scan">
Run duplication scan across the whole repo (not just a wave). Reuses `verify-utility-duplication.py` detection logic via a helper Python block.

```bash
SCAN_JSON=$(mktemp)
PYTHONIOENCODING=utf-8 ${PYTHON_BIN:-python3} - "$PROJECT_MD" "$SCAN_JSON" "$THRESHOLD" <<'PY'
import json, re, subprocess, sys
from collections import defaultdict
from pathlib import Path

project_md = Path(sys.argv[1])
out_path   = Path(sys.argv[2])
threshold  = int(sys.argv[3])

# Reuse detection from verify-utility-duplication.py via import
sys.path.insert(0, str(Path('.claude/scripts').resolve()))
# Direct import not guaranteed available (script uses __main__ pattern) — replicate minimal logic here.

SOURCE_EXTS = {".ts", ".tsx", ".js", ".jsx"}

DECL_PATTERNS = [
    re.compile(r"^\s*export\s+(?:async\s+)?function\s+([a-z][A-Za-z0-9_]*)\s*[<(]", re.M),
    re.compile(r"^\s*export\s+const\s+([a-z][A-Za-z0-9_]*)\s*[:=]\s*(?:async\s+)?(?:\(|function)", re.M),
    re.compile(r"^\s*(?:async\s+)?function\s+([a-z][A-Za-z0-9_]*)\s*[<(]", re.M),
    re.compile(r"^\s*const\s+([a-z][A-Za-z0-9_]*)\s*[:=]\s*(?:async\s+)?\(", re.M),
]

SKIP_NAMES = {"handler","middleware","builder","resolver","getter","setter","loader","validator","guard","plugin","factory","beforeAll","afterAll","beforeEach","afterEach","it","test","describe","expect","use","useEffect","useState","useMemo","useCallback"}
SKIP_PREFIXES = ("handle","on","render","get","set","fetch","load","build","make","with","create","to","from","map","parse","validate","transform","normalize","serialize","deserialize","is","has","can","should")

def _skippable(name):
    if name in SKIP_NAMES: return True
    for p in SKIP_PREFIXES:
        if name.startswith(p) and len(name) > len(p) and name[len(p)].isupper():
            return True
    return False

# git ls-files to scan
try:
    out = subprocess.run(["git","ls-files","*.ts","*.tsx","*.js","*.jsx"],
                         capture_output=True, text=True, check=True).stdout
except Exception:
    out = ""

# Filter out tests, dist, legacy
files = []
for line in out.splitlines():
    l = line.strip()
    if not l: continue
    if "__tests__" in l: continue
    if l.endswith((".test.ts",".test.tsx",".spec.ts",".spec.tsx")): continue
    if "node_modules/" in l or "/dist/" in l or l.startswith("dist/"): continue
    if l.startswith("html/") or l.startswith("html\\"): continue
    p = Path(l)
    if p.exists():
        files.append(p)

# Extract declarations per file
counter = defaultdict(list)  # name → [files]
for f in files:
    try:
        txt = f.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    seen_in_file = set()
    for pat in DECL_PATTERNS:
        for m in pat.finditer(txt):
            n = m.group(1)
            if _skippable(n) or len(n) < 3: continue
            if n in seen_in_file: continue  # same file, multiple patterns
            seen_in_file.add(n)
            counter[n].append(str(f).replace("\\","/"))

# Parse contract names (canonical exports)
contract = set()
if project_md.exists():
    txt = project_md.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^##\s+Shared Utility Contract\s*$(.+?)^##\s+", txt, re.M|re.S)
    if m:
        for row in re.finditer(r"^\|\s*`([A-Za-z_][A-Za-z0-9_]*)`\s*\|", m.group(1), re.M):
            contract.add(row.group(1))

# Rank candidates: contract names first, then by count
candidates = []
for name, locations in counter.items():
    # Exclude the canonical package itself — that file IS the source of truth
    non_canonical = [l for l in locations if "packages/utils" not in l and "packages\\utils" not in l]
    if len(non_canonical) < threshold:
        continue
    candidates.append({
        "name": name,
        "is_contract": name in contract,
        "copy_count": len(non_canonical),
        "locations": non_canonical,
    })

# Sort: contract names first (highest priority), then by count desc
candidates.sort(key=lambda x: (not x["is_contract"], -x["copy_count"], x["name"]))

result = {
    "threshold": threshold,
    "files_scanned": len(files),
    "candidates_total": len(candidates),
    "candidates": candidates,
}
out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
print(f"Scan: {len(files)} files, {len(candidates)} candidates (≥{threshold} copies)")
for c in candidates[:15]:
    flag = " [contract]" if c["is_contract"] else ""
    print(f"  {c['copy_count']:3d}x  {c['name']}{flag}")
if len(candidates) > 15:
    print(f"  ... and {len(candidates)-15} more")
PY

SCAN_EXIT=$?
[ $SCAN_EXIT -ne 0 ] && { echo "⛔ Scan failed"; rm -f "$SCAN_JSON"; exit 1; }
```

If `MODE=scan`, print report and exit. No writes.
</step>

<step name="3_select">
Mode `interactive` or `all`: decide which helpers to extract.

```bash
case "$MODE" in
  scan)
    rm -f "$SCAN_JSON"
    echo ""
    echo "Run /vg:extract-utils --interactive to select helpers to extract"
    echo "Or   /vg:extract-utils --all to extract every candidate above threshold"
    exit 0
    ;;
  extract-one)
    SELECTED="$HELPER_NAME"
    ;;
  all)
    # Extract all contract names first, then top non-contract candidates
    SELECTED=$(${PYTHON_BIN} -c "
import json; d=json.load(open('$SCAN_JSON',encoding='utf-8'))
print('\n'.join(c['name'] for c in d['candidates']))
")
    ;;
  interactive)
    echo ""
    echo "Top candidates (ranked):"
    ${PYTHON_BIN} -c "
import json; d=json.load(open('$SCAN_JSON',encoding='utf-8'))
for i,c in enumerate(d['candidates'][:20],1):
    flag=' [contract]' if c['is_contract'] else ''
    print(f'  {i:2d}. {c[\"copy_count\"]:3d}x  {c[\"name\"]}{flag}')
"
    # AskUserQuestion via orchestrator (Claude tool call) — multi-select
    # Orchestrator: read candidates from $SCAN_JSON and present multi-select
    echo ""
    echo "▸ Orchestrator: use AskUserQuestion (multiSelect: true) to let user pick helpers"
    echo "  Then set SELECTED to newline-separated names and proceed to step 4."
    # Fall through — orchestrator sets SELECTED
    ;;
esac

[ -z "$SELECTED" ] && { echo "⛔ No helpers selected"; exit 1; }
echo ""
echo "Selected for extraction:"
echo "$SELECTED" | head -20
```
</step>

<step name="4_extract_each">
For each selected helper, spawn a dedicated extraction agent.

**Per-helper agent prompt template** (orchestrator spawns one Agent per name):

```
You are extracting ONE duplicate helper function into the canonical @vollxssp/utils
package. Atomic operation: success → commit. Failure → revert.

Helper name: {NAME}
Canonical package: {CANONICAL_PKG} (path: {CANONICAL_DIR}/src/)
Contract module (from PROJECT.md table, or pick sensible one): {MODULE_TS}

## Your steps

1. **Find all declarations** of `{NAME}` in the repo:
   git grep -n -E "^\s*(export\s+)?(function\s+{NAME}|const\s+{NAME}\s*[:=])" -- '*.ts' '*.tsx' '*.js' '*.jsx'

2. **Read each file's implementation** (use Read tool with line offsets).
   Compare implementations — are they identical? Near-identical? Divergent?

3. **Pick canonical signature + body:**
   - If all implementations are ≈ the same → use any (prefer TypeScript-typed over plain JS)
   - If signatures differ → write the MOST PERMISSIVE (union of params, default values preserve old callers' behavior)
   - If bodies diverge meaningfully → ASK (but before asking, consider: are the divergent variants actually the same intent? Many `formatCurrency` variants differ only in hardcoded "USD" vs configurable — consolidate with `currency='USD'` default)

4. **Write canonical to packages/utils/src/{module}.ts:**
   - If module file exists → ADD the export; preserve existing content
   - If module file is new → CREATE with header comment + export
   - Add TypeScript types (not `any`)
   - Add a unit test at packages/utils/src/__tests__/{module}.test.ts (or extend existing)

5. **Update packages/utils/src/index.ts:**
   - Add `export { {NAME} } from './{module}.js';` (respect existing file style — ESM .js extension if other exports use it)

6. **Rewrite each caller file** that had local declaration:
   - DELETE the local `const {NAME} = ...` / `function {NAME} ...` block
   - ADD `import { {NAME} } from '@vollxssp/utils';` at top (merge with existing `@vollxssp/utils` import if present — don't duplicate)
   - If caller passed extra args (e.g., hardcoded locale) → preserve via call-site args, not inline

7. **Typecheck AFFECTED packages only** (skip apps/web if the extraction doesn't touch it, to avoid OOM):
   - Determine affected packages via caller file paths
   - Run `pnpm --filter <each-affected-package> typecheck` (NOT apps/web unless necessary)
   - If apps/web MUST typecheck: first `vg_typecheck_should_bootstrap web && vg_typecheck_bootstrap web` to seed cache

8. **Commit atomically:**
   - Message: `refactor(utils): extract {NAME} ({N} callers → 1 canonical)`
   - Body citation: `Per PROJECT.md Shared Utility Contract. Removes {N} duplicate declarations.`
   - Covers goal: `utility-contract-migration`

## Rules
- NO mutex needed (extractions run sequentially by orchestrator, not parallel)
- NO `--no-verify` on commit — pre-commit hook MUST pass
- Do NOT edit files in `packages/utils/` other than the module + index + test
- Do NOT change call semantics — behavior must be IDENTICAL before/after for all callers
- If typecheck fails, revert your commit via `git reset --hard HEAD~1` and report failure; DO NOT attempt another commit

## Return
Short report (under 150 words):
- canonical signature chosen + why
- N callers rewritten (list paths)
- typecheck result
- commit SHA
- any divergences that needed judgment calls
```

**Orchestrator flow:**

For each name in SELECTED:
1. NARRATE: `## Extracting {name} ({copy_count} callers)...`
2. Spawn Agent (subagent_type=general-purpose, model=${MODEL_EXECUTOR or sonnet})
3. Wait for completion (foreground — sequential, not parallel)
4. Parse report; collect commit SHA
5. If failure → log + skip (don't block other extractions)

Sequential (not parallel) because:
- Parallel extractions can conflict on `index.ts` (both add export → git merge conflict)
- apps/web tsc is heavy — parallel bootstraps blow memory
- Each extraction is fast (~2-5 min) so sequential is acceptable

```bash
EXTRACTED_COUNT=0
FAILED_COUNT=0
COMMITS=""

while IFS= read -r NAME; do
  [ -z "$NAME" ] && continue
  echo ""
  echo "━━━ Extracting $NAME ━━━"
  # Orchestrator: spawn Agent here with prompt template above, substituting {NAME}
  # Wait for completion; capture commit SHA from agent report.
  # Increment counters.
  # (Actual Agent call happens in orchestrator conversation, not bash)
done <<< "$SELECTED"
```
</step>

<step name="5_final_typecheck">
After all extractions, run ONE final typecheck across the monorepo to catch cross-package issues.

```bash
echo ""
echo "━━━ Final monorepo typecheck ━━━"
# Bootstrap once if needed
source .claude/commands/vg/_shared/lib/typecheck-light.sh 2>/dev/null || true
if type -t vg_typecheck_should_bootstrap >/dev/null 2>&1; then
  for pkg in utils api web workers; do
    [ -d "apps/$pkg" -o -d "packages/$pkg" ] || continue
    vg_typecheck_should_bootstrap "$pkg" && vg_typecheck_bootstrap "$pkg"
  done
fi

if command -v pnpm >/dev/null 2>&1; then
  NODE_OPTIONS="--max-old-space-size=${VG_TYPECHECK_HEAP_MB:-8192}" \
    pnpm turbo typecheck 2>&1 | tail -20
  FINAL_EXIT=${PIPESTATUS[0]}
else
  FINAL_EXIT=0
  echo "⚠ pnpm not found — skipping final typecheck"
fi

if [ $FINAL_EXIT -ne 0 ]; then
  echo ""
  echo "⛔ Final typecheck FAILED."
  echo "   Individual extraction commits landed OK but cross-package typing broke."
  echo "   Inspect the output above, fix callers manually, then commit."
fi
```
</step>

<step name="6_summary">
Emit extraction summary.

```bash
echo ""
echo "━━━ Extraction Summary ━━━"
echo "Attempted:  $((EXTRACTED_COUNT + FAILED_COUNT))"
echo "Succeeded:  $EXTRACTED_COUNT"
echo "Failed:     $FAILED_COUNT"
echo ""
if [ $EXTRACTED_COUNT -gt 0 ]; then
  echo "Commits:"
  echo "$COMMITS" | sed 's/^/  /'
fi
echo ""
echo "Next:"
echo "  - Review diff: git log --stat -${EXTRACTED_COUNT}"
echo "  - Run full test suite to validate behavior preserved"
echo "  - Re-run /vg:extract-utils --scan to see remaining duplicates"
```
</step>

</process>

<success_criteria>
- `--scan` mode: prints ranked duplicate candidates, writes nothing
- `--extract <name>`: one helper migrated, 1 commit, typecheck green
- `--all`: every above-threshold helper extracted sequentially, each atomic commit
- Canonical exports appear in `packages/utils/src/index.ts`
- Caller files have `import { X } from '@vollxssp/utils'` replacing local declarations
- Final monorepo typecheck passes
- No behavioral change — existing tests still pass
- Re-run `--scan` after extraction shows reduced duplicate count
</success_criteria>
