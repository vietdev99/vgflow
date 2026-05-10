<step name="0_parse_args">
## Step 0: Parse args + load config

```bash
PLANNING_DIR=".vg"
PROJECT_FILE="${PLANNING_DIR}/PROJECT.md"
FOUNDATION_FILE="${PLANNING_DIR}/FOUNDATION.md"
CONFIG_FILE=".claude/vg.config.md"
DRAFT_FILE="${PLANNING_DIR}/.project-draft.json"
ARCHIVE_DIR="${PLANNING_DIR}/.archive"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$PLANNING_DIR"

# Mode flags (mutually exclusive)
MODE=""
DOC_PATH=""
INLINE_DESC=""

for arg in $ARGUMENTS; do
  case "$arg" in
    --view)        MODE="view" ;;
    --update)      MODE="update" ;;
    --milestone)   MODE="milestone" ;;
    --rewrite)     MODE="rewrite" ;;
    --migrate)     MODE="migrate" ;;
    --init-only)   MODE="init_only" ;;
    --auto)        MODE="auto" ;;
    @*)            DOC_PATH="${arg#@}" ;;
    *)             INLINE_DESC="${INLINE_DESC} ${arg}" ;;
  esac
done

INLINE_DESC=$(echo "$INLINE_DESC" | sed 's/^ *//; s/ *$//')

PROJECT_EXISTS=false; [ -f "$PROJECT_FILE" ] && PROJECT_EXISTS=true
FOUNDATION_EXISTS=false; [ -f "$FOUNDATION_FILE" ] && FOUNDATION_EXISTS=true
CONFIG_EXISTS=false; [ -f "$CONFIG_FILE" ] && CONFIG_EXISTS=true
DRAFT_EXISTS=false; [ -f "$DRAFT_FILE" ] && DRAFT_EXISTS=true

HAS_CODE=false
for d in apps src packages lib; do
  [ -d "$d" ] && HAS_CODE=true && break
done

: # State printing happens in step 0b after collecting more context
```
</step>

<step name="0b_print_state_summary">
## Step 0b: ALWAYS print state summary first (UX — user không cần nhớ flag)

Mỗi lần `/vg:project` chạy, **bắt buộc** hiển thị state header trước khi làm gì khác. User type `/vg:project` (no args) → ngay lập tức biết hiện trạng + được đề xuất action recommended. Không cần đoán flag.

```bash
# Collect rich state info
PROJECT_AGE=""
[ -f "$PROJECT_FILE" ] && PROJECT_AGE=$(${PYTHON_BIN} -c "
import os, datetime
try:
  ts = os.path.getmtime('$PROJECT_FILE')
  age_days = (datetime.datetime.now().timestamp() - ts) / 86400
  print(f'{int(age_days)}d ago' if age_days >= 1 else 'today')
except Exception: print('?')
" 2>/dev/null)

FOUNDATION_AGE=""
[ -f "$FOUNDATION_FILE" ] && FOUNDATION_AGE=$(${PYTHON_BIN} -c "
import os, datetime
try:
  ts = os.path.getmtime('$FOUNDATION_FILE')
  age_days = (datetime.datetime.now().timestamp() - ts) / 86400
  print(f'{int(age_days)}d ago' if age_days >= 1 else 'today')
except Exception: print('?')
" 2>/dev/null)

CONFIG_AGE=""
[ -f "$CONFIG_FILE" ] && CONFIG_AGE=$(${PYTHON_BIN} -c "
import os, datetime
try:
  ts = os.path.getmtime('$CONFIG_FILE')
  age_days = (datetime.datetime.now().timestamp() - ts) / 86400
  print(f'{int(age_days)}d ago' if age_days >= 1 else 'today')
except Exception: print('?')
" 2>/dev/null)

# Detect codebase profile
CODEBASE_HINT=""
[ -d "apps" ] && CODEBASE_HINT="${CODEBASE_HINT}apps/ "
[ -d "packages" ] && CODEBASE_HINT="${CODEBASE_HINT}packages/ "
[ -d "src" ] && CODEBASE_HINT="${CODEBASE_HINT}src/ "
[ -f "package.json" ] && CODEBASE_HINT="${CODEBASE_HINT}package.json "
[ -f "Cargo.toml" ] && CODEBASE_HINT="${CODEBASE_HINT}Cargo.toml "
[ -f "go.mod" ] && CODEBASE_HINT="${CODEBASE_HINT}go.mod "
[ -f "pubspec.yaml" ] && CODEBASE_HINT="${CODEBASE_HINT}pubspec.yaml(Flutter) "
CODEBASE_HINT=$(echo "$CODEBASE_HINT" | sed 's/ *$//')

echo ""
echo "🔍 ━━━ /vg:project — Hiện trạng project ━━━"
echo ""
printf "  📁 %-32s %s\n" "${PLANNING_DIR}/PROJECT.md"      "$([ "$PROJECT_EXISTS" = "true" ]    && echo "✓ exists ($PROJECT_AGE)"    || echo "✗ missing")"
printf "  📁 %-32s %s\n" "${PLANNING_DIR}/FOUNDATION.md"   "$([ "$FOUNDATION_EXISTS" = "true" ] && echo "✓ exists ($FOUNDATION_AGE)" || echo "✗ missing")"
printf "  📁 %-32s %s\n" ".claude/vg.config.md"      "$([ "$CONFIG_EXISTS" = "true" ]     && echo "✓ exists ($CONFIG_AGE)"     || echo "✗ missing")"
printf "  📁 %-32s %s\n" "${PLANNING_DIR}/.project-draft.json" "$([ "$DRAFT_EXISTS" = "true" ]  && echo "⚠ draft in progress"        || echo "✗ none")"
printf "  🗂  %-32s %s\n" "Codebase"                  "$([ "$HAS_CODE" = "true" ]          && echo "✓ detected ($CODEBASE_HINT)" || echo "✗ none (greenfield)")"
echo ""

# Determine state category for routing + suggestion
STATE=""
if [ "$DRAFT_EXISTS" = "true" ]; then
  STATE="draft-in-progress"
elif [ "$PROJECT_EXISTS" = "true" ] && [ "$FOUNDATION_EXISTS" = "true" ]; then
  STATE="fully-initialized"
elif [ "$PROJECT_EXISTS" = "true" ] && [ "$FOUNDATION_EXISTS" = "false" ]; then
  STATE="legacy-v1"
elif [ "$PROJECT_EXISTS" = "false" ] && [ "$HAS_CODE" = "true" ]; then
  STATE="brownfield-fresh"
else
  STATE="greenfield"
fi
echo "  📊 State: ${STATE}"
echo ""
```
</step>

<step name="0c_scan_existing_docs">
## Step 0c: Scan existing docs/code để auto-fill foundation (avoids treating projects with docs as "greenfield")

Trước khi route mode, **luôn** scan các nguồn document hiện có trong repo. Nếu tìm thấy đủ thông tin (README + manifest + ≥1 doc), chuyển state từ `greenfield` → `greenfield-with-docs` hoặc enrich existing state với pre-populated foundation. User KHÔNG phải gõ lại từ đầu những gì đã có trong README/CLAUDE.md/package.json.

**Skip scan nếu:** `STATE = fully-initialized` (đã có FOUNDATION.md authoritative) HOẶC `STATE = draft-in-progress` (đang resume).

```bash
SCAN_RESULTS_FILE="${PLANNING_DIR}/.project-scan.json"

if [ "$STATE" = "fully-initialized" ] || [ "$STATE" = "draft-in-progress" ]; then
  echo "  (scan skipped — authoritative artifacts exist)"
else
  echo "🔍 Scanning existing docs để extract foundation hints..."
  echo ""

  ${PYTHON_BIN} - "$SCAN_RESULTS_FILE" <<'PY'
import json, re, sys, glob
from pathlib import Path

out = Path(sys.argv[1])

scan = {
  "name": None, "description": None,
  "platform_hints": [], "frontend_hints": [], "backend_hints": [],
  "database_hints": [], "hosting_hints": [], "auth_hints": [],
  "monorepo_hints": [], "test_hints": [], "deploy_hints": [],
  "docs_found": [], "rich": False
}

# 1. README + multi-language variants
for readme in ["README.md", "README.vi.md", "readme.md", "Readme.md"]:
    p = Path(readme)
    if not p.exists(): continue
    text = p.read_text(encoding="utf-8", errors="ignore")[:8000]
    m = re.search(r'^#\s+(.+)$', text, re.M)
    if m and not scan["name"]:
        scan["name"] = m.group(1).strip()[:80]
    # First non-empty paragraph after title likely description
    paras = [p.strip() for p in text.split('\n\n') if p.strip() and not p.startswith('#')]
    if paras and not scan["description"]:
        scan["description"] = paras[0][:500]
    scan["docs_found"].append(readme)

# 2. package.json — primary tech stack signal
pkg_path = Path("package.json")
if pkg_path.exists():
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        if not scan["name"]: scan["name"] = pkg.get("name")
        if not scan["description"]: scan["description"] = pkg.get("description")
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        # Frontend
        if "react" in deps: scan["frontend_hints"].append("React")
        if "vite" in deps: scan["frontend_hints"].append("Vite")
        if "next" in deps: scan["frontend_hints"].append("Next.js")
        if "vue" in deps: scan["frontend_hints"].append("Vue")
        if "svelte" in deps or "@sveltejs/kit" in deps: scan["frontend_hints"].append("Svelte/SvelteKit")
        if "@angular/core" in deps: scan["frontend_hints"].append("Angular")
        if "solid-js" in deps: scan["frontend_hints"].append("Solid")
        # Backend
        if "fastify" in deps: scan["backend_hints"].append("Fastify")
        if "express" in deps: scan["backend_hints"].append("Express")
        if "@nestjs/core" in deps: scan["backend_hints"].append("NestJS")
        if "hono" in deps: scan["backend_hints"].append("Hono")
        if "koa" in deps: scan["backend_hints"].append("Koa")
        # Database
        if "mongodb" in deps or "mongoose" in deps: scan["database_hints"].append("MongoDB")
        if "pg" in deps or "postgres" in deps: scan["database_hints"].append("Postgres")
        if "mysql2" in deps or "mysql" in deps: scan["database_hints"].append("MySQL")
        if "better-sqlite3" in deps or "sqlite3" in deps: scan["database_hints"].append("SQLite")
        if "redis" in deps or "ioredis" in deps: scan["database_hints"].append("Redis")
        if "prisma" in deps or "@prisma/client" in deps: scan["database_hints"].append("(Prisma ORM)")
        if "drizzle-orm" in deps: scan["database_hints"].append("(Drizzle ORM)")
        # Mobile / desktop
        if "expo" in deps: scan["platform_hints"].append("mobile-cross (Expo)")
        if "react-native" in deps and "expo" not in deps: scan["platform_hints"].append("mobile-cross (RN bare)")
        if "electron" in deps: scan["platform_hints"].append("desktop (Electron)")
        if "@tauri-apps/api" in deps: scan["platform_hints"].append("desktop (Tauri)")
        # Test
        if "playwright" in deps or "@playwright/test" in deps: scan["test_hints"].append("Playwright")
        if "vitest" in deps: scan["test_hints"].append("Vitest")
        if "jest" in deps: scan["test_hints"].append("Jest")
        if "cypress" in deps: scan["test_hints"].append("Cypress")
        # Auth libs
        if "passport" in deps or "@auth/core" in deps: scan["auth_hints"].append("custom (passport/auth)")
        if "next-auth" in deps: scan["auth_hints"].append("NextAuth.js")
        if "@clerk/nextjs" in deps or "@clerk/clerk-react" in deps: scan["auth_hints"].append("Clerk (3rd-party)")
        if "@auth0/" in str(deps): scan["auth_hints"].append("Auth0 (3rd-party)")
        scan["docs_found"].append("package.json")
    except Exception as e:
        pass

# 3. Other language manifests
if Path("Cargo.toml").exists():
    scan["backend_hints"].append("Rust")
    scan["docs_found"].append("Cargo.toml")
if Path("go.mod").exists():
    scan["backend_hints"].append("Go")
    scan["docs_found"].append("go.mod")
if Path("pubspec.yaml").exists():
    scan["frontend_hints"].append("Flutter")
    scan["platform_hints"].append("mobile-cross (Flutter)")
    scan["docs_found"].append("pubspec.yaml")
if Path("requirements.txt").exists() or Path("pyproject.toml").exists():
    scan["backend_hints"].append("Python")
    scan["docs_found"].append("requirements.txt or pyproject.toml")
if Path("Gemfile").exists():
    scan["backend_hints"].append("Ruby")
    scan["docs_found"].append("Gemfile")

# 4. Monorepo
if Path("pnpm-workspace.yaml").exists() or Path("turbo.json").exists():
    scan["monorepo_hints"].append("pnpm + Turborepo")
elif Path("nx.json").exists():
    scan["monorepo_hints"].append("Nx")
elif Path("lerna.json").exists():
    scan["monorepo_hints"].append("Lerna")
elif Path("rush.json").exists():
    scan["monorepo_hints"].append("Rush")

# 5. Infra / hosting / deploy
if Path("infra/ansible").is_dir() or Path("ansible").is_dir():
    scan["hosting_hints"].append("VPS (Ansible)")
    scan["deploy_hints"].append("Ansible playbooks")
if Path("Dockerfile").exists() or Path("docker-compose.yml").exists() or Path("docker-compose.yaml").exists():
    scan["hosting_hints"].append("Docker")
if Path("vercel.json").exists() or Path(".vercel").is_dir():
    scan["hosting_hints"].append("Vercel")
if Path("netlify.toml").exists():
    scan["hosting_hints"].append("Netlify")
if Path("fly.toml").exists():
    scan["hosting_hints"].append("Fly.io")
if Path("render.yaml").exists():
    scan["hosting_hints"].append("Render")
if Path("railway.json").exists() or Path("railway.toml").exists():
    scan["hosting_hints"].append("Railway")
if Path("serverless.yml").exists() or Path("serverless.yaml").exists():
    scan["hosting_hints"].append("Serverless Framework")
if Path("template.yaml").exists() or Path("samconfig.toml").exists():
    scan["hosting_hints"].append("AWS SAM")
if Path("wrangler.toml").exists():
    scan["hosting_hints"].append("Cloudflare Workers")
if Path(".github/workflows").is_dir():
    scan["deploy_hints"].append("GitHub Actions")
if Path(".gitlab-ci.yml").exists():
    scan["deploy_hints"].append("GitLab CI")

# 6. Auth code patterns
for auth_glob in ["apps/*/src/**/auth*", "src/**/auth*", "apps/*/src/modules/auth"]:
    if any(Path(p).exists() for p in glob.glob(auth_glob, recursive=True)[:1]):
        if not scan["auth_hints"]:
            scan["auth_hints"].append("custom (apps/*/auth code detected)")
        break

# 7. CLAUDE.md — often contains rich project description (per convention)
for claude_md in ["CLAUDE.md", ".claude/CLAUDE.md"]:
    p = Path(claude_md)
    if not p.exists(): continue
    text = p.read_text(encoding="utf-8", errors="ignore")
    # Look for "## Project" or "## Overview" section
    for header in [r'^##\s*Project\b', r'^##\s*Overview\b', r'^##\s*About\b']:
        m = re.search(header + r'[\s\S]*?(?=^##|\Z)', text, re.M)
        if m:
            section = m.group(0).strip()
            if not scan["description"] or len(scan["description"]) < 200:
                scan["description"] = section[:800]
            break
    scan["docs_found"].append(claude_md)

# 8. Brief / spec docs
for pattern in ["docs/**/*.md", "BRIEF.md", "SPEC.md", "RFC*.md", "*-brief.md", "*-spec.md"]:
    for f in glob.glob(pattern, recursive=True)[:3]:
        if f not in scan["docs_found"] and "vendor" not in f and "node_modules" not in f:
            scan["docs_found"].append(f)

# 9. ${PLANNING_DIR}/ deep scan — toàn bộ artifacts từ pipeline trước
planning_dir = Path(".vg")
if planning_dir.is_dir():
    # 9a. PROJECT.md (legacy or current)
    legacy_project = planning_dir / "PROJECT.md"
    if legacy_project.exists():
        text = legacy_project.read_text(encoding="utf-8", errors="ignore")
        if not scan["description"]:
            scan["description"] = text[:800]
        if not scan["name"]:
            m = re.search(r'^#\s+(.+)$', text, re.M)
            if m: scan["name"] = m.group(1).strip()[:80]
        scan["docs_found"].append("${PLANNING_DIR}/PROJECT.md (legacy)")

    # 9b. REQUIREMENTS.md — list of REQ-XX items
    req_file = planning_dir / "REQUIREMENTS.md"
    if req_file.exists():
        text = req_file.read_text(encoding="utf-8", errors="ignore")
        req_count = len(re.findall(r'\b(REQ|R)-?\d+\b', text))
        scan["docs_found"].append(f"${PLANNING_DIR}/REQUIREMENTS.md ({req_count} requirements)")

    # 9c. ROADMAP.md — phase plan
    roadmap_file = planning_dir / "ROADMAP.md"
    if roadmap_file.exists():
        text = roadmap_file.read_text(encoding="utf-8", errors="ignore")
        phase_count = len(re.findall(r'^##?\s*Phase\s+[\d.]+', text, re.M))
        scan["docs_found"].append(f"${PLANNING_DIR}/ROADMAP.md ({phase_count} phases)")

    # 9d. STATE.md — pipeline progress snapshot
    state_file = planning_dir / "STATE.md"
    if state_file.exists():
        scan["docs_found"].append("${PLANNING_DIR}/STATE.md (pipeline state snapshot)")

    # 9e. SCOPE.md / PROJECT-SCOPE.md
    for scope_name in ["SCOPE.md", "PROJECT-SCOPE.md"]:
        scope_file = planning_dir / scope_name
        if scope_file.exists():
            scan["docs_found"].append(f"${PLANNING_DIR}/{scope_name}")

    # 9f. phases/ directory — count + extract phase titles
    phases_dir = planning_dir / "phases"
    if phases_dir.is_dir():
        phase_dirs = sorted([p for p in phases_dir.iterdir() if p.is_dir()])
        if phase_dirs:
            # Count phases by status (look for SUMMARY.md, UAT.md as completion markers)
            completed = sum(1 for p in phase_dirs if (p / "UAT.md").exists())
            in_progress = sum(1 for p in phase_dirs if (p / "SUMMARY.md").exists() and not (p / "UAT.md").exists())
            scan["docs_found"].append(
                f"${PLANNING_DIR}/phases/ ({len(phase_dirs)} dirs: {completed} accepted, {in_progress} in-progress)"
            )
            # Extract titles of latest 3 phases for context
            for p in phase_dirs[-3:]:
                # phase name from dir like "07.10.1-user-drawer-tabs" → human title
                parts = p.name.split("-", 1)
                if len(parts) == 2:
                    scan["docs_found"].append(f"   • Phase {parts[0]}: {parts[1].replace('-', ' ')}")

    # 9g. intel/ — codebase intel files
    intel_dir = planning_dir / "intel"
    if intel_dir.is_dir():
        intel_count = len(list(intel_dir.glob("*.md")))
        if intel_count > 0:
            scan["docs_found"].append(f"${PLANNING_DIR}/intel/ ({intel_count} intel files)")

    # 9h. codebase/ — codebase mapping docs
    codebase_dir = planning_dir / "codebase"
    if codebase_dir.is_dir():
        codebase_count = len(list(codebase_dir.glob("*.md")))
        if codebase_count > 0:
            scan["docs_found"].append(f"${PLANNING_DIR}/codebase/ ({codebase_count} mapping docs)")

    # 9i. research/ — pre-roadmap research
    research_dir = planning_dir / "research"
    if research_dir.is_dir():
        research_count = len(list(research_dir.glob("*.md")))
        if research_count > 0:
            scan["docs_found"].append(f"${PLANNING_DIR}/research/ ({research_count} research docs)")

    # 9j. design refs — v2.30+ 2-tier (phase-scoped + project-shared) +
    # legacy compat. Sum design refs across all known locations.
    design_count = 0
    # Tier 2: project-shared (.vg/design-system/)
    shared_dir = planning_dir.parent / ".vg" / "design-system"
    if shared_dir.is_dir():
        design_count += len(list(shared_dir.rglob("*.md"))) + len(list(shared_dir.rglob("*.png")))
    # Tier 1: phase-scoped (.vg/phases/{N}/design/)
    phases_dir = planning_dir.parent / ".vg" / "phases"
    if phases_dir.is_dir():
        for ph in phases_dir.iterdir():
            phd = ph / "design"
            if phd.is_dir():
                design_count += len(list(phd.rglob("*.md"))) + len(list(phd.rglob("*.png")))
    # Tier 3: legacy (.planning/design-normalized/, .vg/design-normalized/)
    for legacy in (planning_dir / "design-normalized", planning_dir.parent / ".vg" / "design-normalized"):
        if legacy.is_dir():
            design_count += len(list(legacy.rglob("*.md"))) + len(list(legacy.rglob("*.png")))
    if design_count > 0:
        scan["docs_found"].append(f"design refs across phase/shared/legacy ({design_count} files)")

    # 9k. milestones/ — completed milestone archives
    milestones_dir = planning_dir / "milestones"
    if milestones_dir.is_dir():
        milestone_count = len(list(milestones_dir.iterdir()))
        if milestone_count > 0:
            scan["docs_found"].append(f"${PLANNING_DIR}/milestones/ ({milestone_count} archived milestones)")

    # 9l. Top-level loose docs in ${PLANNING_DIR}/
    for f in planning_dir.glob("*.md"):
        if f.name not in {"PROJECT.md", "FOUNDATION.md", "REQUIREMENTS.md", "ROADMAP.md", "STATE.md", "SCOPE.md", "PROJECT-SCOPE.md"}:
            scan["docs_found"].append(f"${PLANNING_DIR}/{f.name}")

# 10. Existing vg.config.md (already-confirmed config — highest trust)
if Path(".claude/vg.config.md").exists():
    scan["docs_found"].append(".claude/vg.config.md (existing config)")

# Determine "richness": if scan found enough info to skip pure-greenfield
non_empty_buckets = sum(1 for k in [
    "frontend_hints","backend_hints","database_hints","hosting_hints",
    "platform_hints","auth_hints","monorepo_hints"
] if scan[k])
scan["rich"] = (
    scan["name"] is not None and
    (scan["description"] is not None or non_empty_buckets >= 2) and
    len(scan["docs_found"]) >= 1
)

out.write_text(json.dumps(scan, indent=2, ensure_ascii=False), encoding="utf-8")

# Print human summary
print(f"  📄 Docs detected: {len(scan['docs_found'])}")
for d in scan["docs_found"][:8]:
    print(f"     • {d}")
if len(scan["docs_found"]) > 8:
    print(f"     • ...and {len(scan['docs_found']) - 8} more")
print()
print("  🤖 Foundation hints extracted:")
if scan["name"]:        print(f"     • Name:       {scan['name']}")
if scan["description"]: print(f"     • Description: {scan['description'][:80]}...")
if scan["platform_hints"]: print(f"     • Platform:   {', '.join(scan['platform_hints'])}")
if scan["frontend_hints"]: print(f"     • Frontend:   {', '.join(scan['frontend_hints'])}")
if scan["backend_hints"]:  print(f"     • Backend:    {', '.join(scan['backend_hints'])}")
if scan["database_hints"]: print(f"     • Database:   {', '.join(scan['database_hints'])}")
if scan["hosting_hints"]:  print(f"     • Hosting:    {', '.join(scan['hosting_hints'])}")
if scan["auth_hints"]:     print(f"     • Auth:       {', '.join(scan['auth_hints'])}")
if scan["monorepo_hints"]: print(f"     • Monorepo:   {', '.join(scan['monorepo_hints'])}")
if scan["test_hints"]:     print(f"     • Test:       {', '.join(scan['test_hints'])}")
if scan["deploy_hints"]:   print(f"     • Deploy:     {', '.join(scan['deploy_hints'])}")
print()
print(f"  Result: {'RICH (auto-fill ready)' if scan['rich'] else 'SPARSE (need user input)'}")
PY

  # Read result + upgrade STATE if scan was rich
  if [ -f "$SCAN_RESULTS_FILE" ]; then
    SCAN_RICH=$(${PYTHON_BIN} -c "import json; print(json.load(open('${SCAN_RESULTS_FILE}'))['rich'])" 2>/dev/null)
    if [ "$SCAN_RICH" = "True" ] && [ "$STATE" = "greenfield" ]; then
      STATE="greenfield-with-docs"
      echo "  📊 State upgraded: greenfield → greenfield-with-docs (scan results sufficient)"
    elif [ "$SCAN_RICH" = "True" ] && [ "$STATE" = "brownfield-fresh" ]; then
      STATE="brownfield-with-docs"
      echo "  📊 State upgraded: brownfield-fresh → brownfield-with-docs"
    fi
  fi
  echo ""
fi
```
</step>
