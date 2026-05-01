#!/bin/bash
# typecheck-light.sh — light typecheck modes for /vg:build + /vg:review.
#
# Problem:
#   apps/web tsc --noEmit is heavy (~3-5 min cold, OOM at default 4GB heap).
#   Per-task typecheck in a 5-task wave = 25 min just on TS checking.
#   Review/build steps that also typecheck compound the cost.
#
# Solution — 3 modes:
#
#   1. BOOTSTRAP — run once per session to populate .tsbuildinfo cache.
#      Heavy (3-5 min) but 1-shot. Subsequent incremental runs drop to 10-30s.
#
#   2. INCREMENTAL — standard fast check leveraging cache. Default mode.
#      Runs full tsc but reads .tsbuildinfo for diff-only checking.
#      Typical: 10-30s after bootstrap.
#
#   3. ISOLATED <file...> — per-file isolatedModules check. Fastest per file
#      (~2-5s) but only catches syntax/local type errors, not cross-file
#      signature mismatches. Use for rapid iteration; wave-gate follows with
#      INCREMENTAL to catch cross-file issues.
#
# Memory budget via NODE_OPTIONS defaults to 8GB (tuneable).
# Heap bumps applied INSIDE the command — caller doesn't need to export.
#
# Usage:
#   source .claude/commands/vg/_shared/lib/typecheck-light.sh
#   vg_typecheck_bootstrap <pkg>          # one-shot cold
#   vg_typecheck_incremental <pkg>        # default fast check
#   vg_typecheck_isolated <file...>       # per-file (weak coverage but fast)
#   vg_typecheck_should_bootstrap <pkg>   # 0 if bootstrap needed, 1 if skip
#   vg_typecheck_narrow <pkg> <base-ref>  # v1.14.3: check only files changed since ref
#   vg_typecheck_adaptive <pkg> [base-ref]# v1.14.3: auto-select mode by size + OOM history

set -u

VG_TYPECHECK_HEAP_MB="${VG_TYPECHECK_HEAP_MB:-8192}"
VG_TYPECHECK_HEAP_BOOTSTRAP_MB="${VG_TYPECHECK_HEAP_BOOTSTRAP_MB:-16384}"
# v1.14.3 cache-bootstrap defaults (portable — not project-specific)
VG_CACHE_BOOTSTRAP_STRATEGY="${VG_CACHE_BOOTSTRAP_STRATEGY:-auto}"  # auto | watch | tsgo | chunked | skip
VG_CACHE_BOOTSTRAP_WATCH_TIMEOUT="${VG_CACHE_BOOTSTRAP_WATCH_TIMEOUT:-300}"  # seconds
VG_CACHE_BOOTSTRAP_CHUNK_SIZE="${VG_CACHE_BOOTSTRAP_CHUNK_SIZE:-400}"       # files per chunk

# Resolve package name to monorepo path. Checks apps/<name> first.
_vg_typecheck_resolve_path() {
  local pkg="$1"
  # Accept full name (@vollxssp/web) or short (web)
  local short="${pkg##*/}"
  if [ -d "apps/${short}" ]; then
    echo "apps/${short}"
  elif [ -d "packages/${short}" ]; then
    echo "packages/${short}"
  else
    # Let caller handle not-found
    echo ""
  fi
}

# Is the .tsbuildinfo cache present + non-empty?
_vg_typecheck_cache_exists() {
  local pkg_path="$1"
  [ -s "${pkg_path}/.tsbuildinfo" ] || [ -s "${pkg_path}/tsconfig.tsbuildinfo" ]
}

# Return 0 (true) if bootstrap is needed (cold start), 1 (false) if cache exists.
# Caller can skip bootstrap if not needed.
vg_typecheck_should_bootstrap() {
  local pkg="$1"
  local path
  path=$(_vg_typecheck_resolve_path "$pkg")
  if [ -z "$path" ]; then
    echo "⚠ vg_typecheck: package '$pkg' not found" >&2
    return 0   # treat as needs-bootstrap (safer)
  fi
  if _vg_typecheck_cache_exists "$path"; then
    return 1   # cache present — skip bootstrap
  fi
  return 0
}

# Bootstrap: run cold tsc with max heap to populate .tsbuildinfo.
# 1-shot per session. Subsequent incremental runs benefit.
vg_typecheck_bootstrap() {
  local pkg="$1"
  local path
  path=$(_vg_typecheck_resolve_path "$pkg")
  if [ -z "$path" ]; then
    echo "⛔ vg_typecheck_bootstrap: package '$pkg' not found" >&2
    return 1
  fi

  if _vg_typecheck_cache_exists "$path"; then
    echo "✓ vg_typecheck: cache exists at ${path}/.tsbuildinfo — skipping bootstrap"
    return 0
  fi

  echo "▸ vg_typecheck: bootstrapping ${pkg} (first run — expect 3-5 min + ${VG_TYPECHECK_HEAP_BOOTSTRAP_MB}MB heap)"
  local start
  start=$(date +%s)

  ( cd "$path" && NODE_OPTIONS="--max-old-space-size=${VG_TYPECHECK_HEAP_BOOTSTRAP_MB}" pnpm run typecheck )
  local rc=$?

  local elapsed=$(( $(date +%s) - start ))
  if [ $rc -eq 0 ]; then
    local size
    size=$(du -h "${path}/.tsbuildinfo" 2>/dev/null | awk '{print $1}' || echo "?")
    echo "✓ vg_typecheck: bootstrap done in ${elapsed}s — .tsbuildinfo ${size}. Subsequent runs will be fast."
  else
    echo "⛔ vg_typecheck: bootstrap FAILED (${elapsed}s, exit ${rc})" >&2
  fi
  return $rc
}

# Incremental: standard check with cache + moderate heap.
# Default agent + wave-gate mode. v1.14.3+: if tsgo available, use it —
# dramatically faster + lower RAM than node tsc (1s warm vs 10-30s).
vg_typecheck_incremental() {
  local pkg="$1"
  local path
  path=$(_vg_typecheck_resolve_path "$pkg")
  if [ -z "$path" ]; then
    echo "⛔ vg_typecheck_incremental: package '$pkg' not found" >&2
    return 1
  fi

  # Prefer tsgo if available — it honors .tsbuildinfo cache AND has
  # dramatically lower memory footprint than node tsc on large projects.
  if _vg_cache_detect_tsgo; then
    echo "▸ vg_typecheck: tsgo incremental on ${pkg} (native — no heap limit)"
    local start
    start=$(date +%s)
    ( cd "$path" && tsgo --noEmit )
    local rc=$?
    local elapsed=$(( $(date +%s) - start ))
    if [ $rc -eq 0 ]; then
      echo "✓ vg_typecheck: tsgo done in ${elapsed}s"
    else
      echo "⛔ vg_typecheck: tsgo FAILED (${elapsed}s, exit ${rc})" >&2
    fi
    return $rc
  fi

  if ! _vg_typecheck_cache_exists "$path"; then
    echo "⚠ vg_typecheck: no cache for ${pkg} — first run will be cold, bumping heap"
    # Auto-upgrade to bootstrap mode if cache missing
    vg_typecheck_bootstrap "$pkg"
    return $?
  fi

  echo "▸ vg_typecheck: incremental ${pkg} (${VG_TYPECHECK_HEAP_MB}MB heap)"
  local start
  start=$(date +%s)

  ( cd "$path" && NODE_OPTIONS="--max-old-space-size=${VG_TYPECHECK_HEAP_MB}" pnpm run typecheck )
  local rc=$?

  local elapsed=$(( $(date +%s) - start ))
  if [ $rc -eq 0 ]; then
    echo "✓ vg_typecheck: incremental done in ${elapsed}s"
  else
    echo "⛔ vg_typecheck: incremental FAILED (${elapsed}s, exit ${rc})" >&2
  fi
  return $rc
}

# Isolated per-file: fastest, weakest coverage.
# Use in per-task agent loops when speed > cross-file safety.
# Wave gate MUST follow with incremental mode.
#
# NOTE: requires apps/<pkg>/tsconfig.json to have isolatedModules: true
#       (apps/web already does).
vg_typecheck_isolated() {
  local files=("$@")
  if [ "${#files[@]}" -eq 0 ]; then
    echo "⛔ vg_typecheck_isolated: no files given" >&2
    return 2
  fi

  # Filter to .ts/.tsx/.js/.jsx files that exist
  local valid=()
  for f in "${files[@]}"; do
    if [ -f "$f" ] && [[ "$f" =~ \.(ts|tsx|js|jsx)$ ]]; then
      valid+=("$f")
    fi
  done

  if [ "${#valid[@]}" -eq 0 ]; then
    echo "✓ vg_typecheck_isolated: no TS/JS files to check (non-source change)"
    return 0
  fi

  echo "▸ vg_typecheck: isolated-modules check on ${#valid[@]} files (~2-5s each)"
  local start
  start=$(date +%s)

  # Group files by their closest tsconfig.json (usually apps/<pkg>/tsconfig.json)
  # Simplest: run one tsc per file using its parent package's tsconfig.
  local failed=0
  for f in "${valid[@]}"; do
    # Find the nearest tsconfig up the tree
    local dir
    dir=$(dirname "$f")
    local tsconfig=""
    while [ "$dir" != "." ] && [ "$dir" != "/" ]; do
      if [ -f "${dir}/tsconfig.json" ]; then
        tsconfig="${dir}/tsconfig.json"
        break
      fi
      dir=$(dirname "$dir")
    done

    if [ -z "$tsconfig" ]; then
      echo "  ⚠ ${f}: no tsconfig.json found — skipping"
      continue
    fi

    # Run per-file check with the tsconfig's settings (minus include/exclude)
    # Use --noEmit + --skipLibCheck for speed. isolatedModules inherited from tsconfig.
    local pkg_dir
    pkg_dir=$(dirname "$tsconfig")
    local rel_file
    rel_file=$(realpath --relative-to="$pkg_dir" "$f" 2>/dev/null || python -c "import os,sys; print(os.path.relpath('$f','$pkg_dir'))")

    ( cd "$pkg_dir" && NODE_OPTIONS="--max-old-space-size=2048" \
      npx tsc --noEmit --skipLibCheck --isolatedModules --project tsconfig.json --incremental false \
      "$rel_file" 2>&1 | tail -5 ) || failed=$((failed + 1))
  done

  local elapsed=$(( $(date +%s) - start ))
  if [ $failed -eq 0 ]; then
    echo "✓ vg_typecheck: isolated check done in ${elapsed}s (${#valid[@]} files pass)"
    return 0
  else
    echo "⛔ vg_typecheck: isolated check — ${failed}/${#valid[@]} file(s) failed in ${elapsed}s"
    return 1
  fi
}

# ──────────────────────────────────────────────────────────────────
# CACHE BOOTSTRAP — create .tsbuildinfo for a package that never
# had it (cold-check OOMs repeatedly). Generic: works for any TS
# project with `"incremental": true` in tsconfig.
#
# Strategy tiers (auto-selected):
#
#   1. tsgo     — if `tsgo` on PATH, use it (Rust-based tsc, 10x, low RAM)
#   2. watch    — spawn `tsc -w` background, poll for .tsbuildinfo, kill
#                  (tsserver incremental loader avoids peak-mem batch OOM)
#   3. chunked  — split tsconfig include into N-file chunks, check each
#                  with small heap; cache sections over runs
#   4. skip     — give up, return non-zero — caller falls back to narrow
#
# Override via VG_CACHE_BOOTSTRAP_STRATEGY env (auto|watch|tsgo|chunked|skip).
# Portable: no hardcoded pkg names/paths — reads tsconfig.json per pkg.

# Detect tsgo (native tsc re-impl) on PATH
_vg_cache_detect_tsgo() {
  command -v tsgo >/dev/null 2>&1
}

# Bootstrap via tsgo — fastest, lowest RAM
_vg_cache_bootstrap_tsgo() {
  local pkg_path="$1"
  echo "▸ cache-bootstrap[tsgo]: running on $pkg_path"
  ( cd "$pkg_path" && tsgo --noEmit ) 2>&1 | tail -5
  return $?
}

# Bootstrap via watch mode — spawn tsc -w, wait for first .tsbuildinfo
# write, then kill. Watch mode loads files incrementally through the
# type graph — peak RAM significantly lower than batch tsc.
_vg_cache_bootstrap_watch() {
  local pkg_path="$1"
  local timeout_s="${2:-${VG_CACHE_BOOTSTRAP_WATCH_TIMEOUT}}"
  local cache_file="${pkg_path}/.tsbuildinfo"

  # If tsconfig specifies custom tsBuildInfoFile, honor it
  local custom_path
  custom_path=$(${PYTHON_BIN:-python3} - "${pkg_path}/tsconfig.json" <<'PY' 2>/dev/null
import json, sys, re
try:
    # tsconfig may have trailing commas / comments — strip naively
    raw = open(sys.argv[1], encoding='utf-8').read()
    raw = re.sub(r'//[^\n]*', '', raw)
    raw = re.sub(r'/\*.*?\*/', '', raw, flags=re.S)
    raw = re.sub(r',(\s*[}\]])', r'\1', raw)
    cfg = json.loads(raw)
    p = cfg.get('compilerOptions', {}).get('tsBuildInfoFile')
    if p: print(p)
except Exception:
    pass
PY
)
  [ -n "$custom_path" ] && cache_file="${pkg_path}/${custom_path}"

  echo "▸ cache-bootstrap[watch]: ${pkg_path} (timeout ${timeout_s}s)"
  echo "  target cache: ${cache_file}"

  # Start tsc -w in background; record PID to a temp file so we can
  # find the actual node process (subshell $! may point to npx wrapper
  # which forks before tsc — killing npx leaves tsc orphaned on Windows).
  local pid_file
  pid_file=$(mktemp)
  ( cd "$pkg_path" && \
    NODE_OPTIONS="--max-old-space-size=${VG_TYPECHECK_HEAP_BOOTSTRAP_MB}" \
    npx tsc --noEmit --watch --preserveWatchOutput >/dev/null 2>&1 & echo $! > "$pid_file"; wait ) &
  local wrapper_pid=$!

  # Cross-platform kill helper — reliably kills tsc on Windows (Git Bash)
  _vg_kill_tree() {
    local target_pid="$1"
    # Try unix kill first
    kill "$target_pid" 2>/dev/null
    # On Windows (Git Bash), also kill child node processes by workload heuristic
    if [ -n "${WINDIR:-}" ] && command -v taskkill >/dev/null 2>&1; then
      # Kill any node.exe using >2GB RAM in our session (likely our tsc -w)
      for pid in $(tasklist //FO CSV 2>/dev/null | awk -F'"' '/^"node.exe"/ {
        gsub(",","",$10); gsub(" K","",$10);
        if ($10+0 > 2000000) print $4
      }' | head -3); do
        taskkill //F //PID "$pid" >/dev/null 2>&1 || true
      done
    fi
  }

  # Poll every 5s for cache file appearance
  local start_ts
  start_ts=$(date +%s)
  while :; do
    sleep 5
    if [ -f "$cache_file" ] && [ -s "$cache_file" ]; then
      _vg_kill_tree "$wrapper_pid"
      rm -f "$pid_file"
      local cache_size
      cache_size=$(du -h "$cache_file" 2>/dev/null | awk '{print $1}')
      local elapsed=$(( $(date +%s) - start_ts ))
      echo "✓ cache-bootstrap[watch]: cache created ${cache_size} in ${elapsed}s"
      return 0
    fi
    if ! kill -0 "$wrapper_pid" 2>/dev/null; then
      rm -f "$pid_file"
      echo "⚠ cache-bootstrap[watch]: tsc -w exited early (may have crashed)"
      return 1
    fi
    local elapsed=$(( $(date +%s) - start_ts ))
    if [ "$elapsed" -ge "$timeout_s" ]; then
      echo "⚠ cache-bootstrap[watch]: timeout ${timeout_s}s — killing watch"
      _vg_kill_tree "$wrapper_pid"
      rm -f "$pid_file"
      return 1
    fi
  done
}

# Bootstrap via chunked check — split tsconfig.include into chunks,
# check each with smaller heap. Each chunk partially populates cache.
_vg_cache_bootstrap_chunked() {
  local pkg_path="$1"
  local chunk_size="${2:-${VG_CACHE_BOOTSTRAP_CHUNK_SIZE}}"

  # Collect source files from src/
  local src_dir="${pkg_path}/src"
  [ ! -d "$src_dir" ] && { echo "⚠ cache-bootstrap[chunked]: no src/ dir"; return 1; }

  local files
  mapfile -t files < <(find "$src_dir" -type f \( -name '*.ts' -o -name '*.tsx' \) \
                        ! -name '*.test.ts' ! -name '*.test.tsx' ! -name '*.spec.ts' ! -name '*.spec.tsx' \
                        | sed "s|^${pkg_path}/||")
  local total=${#files[@]}
  [ "$total" -eq 0 ] && { echo "⚠ cache-bootstrap[chunked]: no source files"; return 1; }

  # Auto-fit: if total <= chunk_size, chunks would be 1 = no chunking = OOM risk.
  # Divide to get at least 4 chunks so big cross-file deps load in phases.
  if [ "$total" -le "$chunk_size" ]; then
    chunk_size=$(( (total + 3) / 4 ))  # ceiling div by 4
    echo "▸ cache-bootstrap[chunked]: auto-fit chunk_size=${chunk_size} (total=${total} ≤ original chunk_size)"
  fi
  local chunks=$(( (total + chunk_size - 1) / chunk_size ))
  echo "▸ cache-bootstrap[chunked]: ${total} files → ${chunks} chunks of ${chunk_size}"

  # Process each chunk
  local i=0
  local chunk_num=1
  while [ "$i" -lt "$total" ]; do
    local end=$(( i + chunk_size ))
    [ "$end" -gt "$total" ] && end=$total
    local chunk=("${files[@]:i:chunk_size}")

    echo "  chunk ${chunk_num}/${chunks} (files ${i}..${end})"

    # Build temp tsconfig for this chunk
    local tmp_cfg="${pkg_path}/tsconfig.chunk-bootstrap.json"
    ${PYTHON_BIN:-python3} - "$tmp_cfg" "${chunk[@]}" <<'PY'
import json, sys
out = sys.argv[1]
files = sys.argv[2:]
json.dump({"extends": "./tsconfig.json", "include": files}, open(out, "w", encoding="utf-8"), indent=2)
PY

    ( cd "$pkg_path" && \
      NODE_OPTIONS="--max-old-space-size=${VG_TYPECHECK_HEAP_MB}" \
      npx tsc --noEmit --skipLibCheck -p tsconfig.chunk-bootstrap.json ) 2>&1 | tail -3
    local rc=${PIPESTATUS[0]}
    rm -f "$tmp_cfg"
    if [ "$rc" -eq 134 ] || [ "$rc" -eq 137 ]; then
      # Log OOM so adaptive skips bootstrap on next call
      local oom_log="${pkg_path}/.tsbuildinfo-oom-log"
      echo "$(date +%s) chunked-bootstrap OOM chunk=${chunk_num} rc=${rc}" >> "$oom_log"
      echo "⛔ chunk ${chunk_num} OOM (rc=$rc) — aborting chunked strategy"
      return 1
    fi
    if [ "$rc" -ne 0 ]; then
      echo "⚠ chunk ${chunk_num} failed (rc=$rc) — continuing"
    fi

    i=$end
    chunk_num=$((chunk_num + 1))
  done

  # After all chunks, the cache may be partial but present — try final full incremental
  if _vg_typecheck_cache_exists "$pkg_path"; then
    echo "✓ cache-bootstrap[chunked]: partial cache seeded"
    return 0
  fi
  echo "⚠ cache-bootstrap[chunked]: no cache written (chunks may have been too small)"
  return 1
}

# Main entrypoint — auto-select strategy
# Args: pkg
# Returns: 0 if cache now exists, 1 if all strategies failed
vg_typecheck_cache_bootstrap() {
  local pkg="$1"
  local path
  path=$(_vg_typecheck_resolve_path "$pkg")
  if [ -z "$path" ]; then
    echo "⛔ vg_typecheck_cache_bootstrap: package '$pkg' not found" >&2
    return 1
  fi

  # Already warm?
  if _vg_typecheck_cache_exists "$path"; then
    echo "✓ vg_typecheck_cache_bootstrap: ${pkg} already warm"
    return 0
  fi

  # Tsconfig must exist + have incremental enabled (check RESOLVED config
  # via `tsc --showConfig` since `incremental` may be inherited from an
  # `extends:` base config, not in the local file).
  if [ ! -f "${path}/tsconfig.json" ]; then
    echo "⚠ ${pkg}: no tsconfig.json — cannot bootstrap cache"
    return 1
  fi
  local resolved_incremental
  resolved_incremental=$(cd "$path" && npx tsc --showConfig 2>/dev/null \
    | ${PYTHON_BIN:-python3} -c "
import json, sys
try:
    cfg = json.load(sys.stdin)
    print(str(cfg.get('compilerOptions', {}).get('incremental', False)).lower())
except Exception:
    print('unknown')
" 2>/dev/null)
  if [ "$resolved_incremental" != "true" ]; then
    echo "⚠ ${pkg}: resolved tsconfig has incremental=${resolved_incremental} — cache unavailable"
    echo "  Add \"incremental\": true to compilerOptions (or extends chain), then retry"
    return 1
  fi

  local strat="${VG_CACHE_BOOTSTRAP_STRATEGY}"
  if [ "$strat" = "skip" ]; then
    echo "▸ cache-bootstrap: skipped (VG_CACHE_BOOTSTRAP_STRATEGY=skip)"
    return 1
  fi

  # Auto-select if not forced
  if [ "$strat" = "auto" ]; then
    if _vg_cache_detect_tsgo; then
      strat="tsgo"
    else
      # Default: try watch first (universal), fallback to chunked
      strat="watch"
    fi
  fi

  case "$strat" in
    tsgo)     _vg_cache_bootstrap_tsgo "$path"    && return 0 ;;
    watch)    _vg_cache_bootstrap_watch "$path"   && return 0 ;;
    chunked)  _vg_cache_bootstrap_chunked "$path" && return 0 ;;
    *)        echo "⚠ unknown strategy '$strat'"; return 1 ;;
  esac

  # If forced strategy failed AND strategy was auto, try fallback chain
  if [ "${VG_CACHE_BOOTSTRAP_STRATEGY:-auto}" = "auto" ]; then
    echo "▸ cache-bootstrap: ${strat} failed, trying chunked fallback"
    _vg_cache_bootstrap_chunked "$path" && return 0
  fi

  # All strategies exhausted — log a "bootstrap-fail" event so adaptive
  # decision tree skips bootstrap on future calls (respects 7-day window).
  local oom_log="${path}/.tsbuildinfo-oom-log"
  echo "$(date +%s) bootstrap-fail all-strategies pkg=${pkg}" >> "$oom_log"

  echo "⛔ vg_typecheck_cache_bootstrap: all strategies failed for ${pkg}"
  echo "  Event logged to ${oom_log} — adaptive will skip bootstrap for 7 days"
  echo "  Alternatives: (a) install tsgo, (b) implement project references"
  return 1
}

# ──────────────────────────────────────────────────────────────────
# NARROW mode — check ONLY files changed since a base git ref.
#
# Strategy: build a temp tsconfig that extends the package's main
# tsconfig but overrides `include` with just the changed files.
# Catches the same class of errors as full check (paths mapping,
# @scoped imports, isolatedModules rules) but on a small scope.
#
# Miss: cross-file type narrowing where an unchanged file CALLS a
# changed signature. Wave-gate should follow up with incremental if
# possible; otherwise log debt.
#
# Args: pkg base-ref
# Returns: exit code from tsc (0 = clean, non-zero = errors)
vg_typecheck_narrow() {
  local pkg="$1"
  local base_ref="${2:-HEAD}"
  local path
  path=$(_vg_typecheck_resolve_path "$pkg")
  if [ -z "$path" ]; then
    echo "⛔ vg_typecheck_narrow: package '$pkg' not found" >&2
    return 1
  fi

  # Gather changed files under this package's tree, relative to package dir
  local changed
  changed=$(git diff --name-only "$base_ref" -- "$path" 2>/dev/null \
            | grep -E '\.(ts|tsx)$' \
            | sed "s|^${path}/||")

  if [ -z "$changed" ]; then
    echo "✓ vg_typecheck_narrow: no .ts/.tsx changes under ${path} since ${base_ref} — skip"
    return 0
  fi

  local file_count
  file_count=$(echo "$changed" | wc -l | tr -d ' ')
  echo "▸ vg_typecheck: narrow check on ${file_count} files in ${pkg} (changed since ${base_ref})"

  # Build temp tsconfig via python (portable JSON gen)
  local tmp_cfg="${path}/tsconfig.narrow-check.json"
  ${PYTHON_BIN:-python3} - "$tmp_cfg" "$changed" <<'PY'
import json, sys
out = sys.argv[1]
files = [line for line in sys.argv[2].splitlines() if line.strip()]
json.dump({"extends": "./tsconfig.json", "include": files}, open(out, "w", encoding="utf-8"), indent=2)
PY

  local start
  start=$(date +%s)
  ( cd "$path" && NODE_OPTIONS="--max-old-space-size=${VG_TYPECHECK_HEAP_MB}" \
    npx tsc --noEmit --skipLibCheck -p tsconfig.narrow-check.json )
  local rc=$?
  local elapsed=$(( $(date +%s) - start ))

  rm -f "$tmp_cfg"

  if [ $rc -eq 0 ]; then
    echo "✓ vg_typecheck: narrow check passed in ${elapsed}s (${file_count} files)"
  else
    echo "⛔ vg_typecheck: narrow check FAILED (${elapsed}s, exit ${rc})" >&2
  fi
  return $rc
}

# ──────────────────────────────────────────────────────────────────
# ADAPTIVE — auto-select mode based on project size + OOM history.
#
# Decision tree:
#   1. Package < 500 files → full incremental (small project, always works)
#   2. Package < 2000 files + cache exists → incremental (fast)
#   3. Package ≥ 2000 files OR prior OOM recorded for this pkg
#      → narrow (changed files only) + log debt
#   4. If narrow mode and base_ref not provided → default to HEAD~1
#
# OOM history: recorded in ${CANONICAL_DIR}/.tsbuildinfo-oom-log
# Each line = ISO timestamp of an OOM event. Older than 7d auto-pruned.
#
# Args: pkg [base-ref]
vg_typecheck_adaptive() {
  local pkg="$1"
  local base_ref="${2:-HEAD~1}"
  local path
  path=$(_vg_typecheck_resolve_path "$pkg")
  if [ -z "$path" ]; then
    echo "⛔ vg_typecheck_adaptive: package '$pkg' not found" >&2
    return 1
  fi

  # Config override: VG_TYPECHECK_STRATEGY env or config var forces mode
  # Values: auto (default), full, narrow, bootstrap, skip
  local forced="${VG_TYPECHECK_STRATEGY:-auto}"
  case "$forced" in
    skip)       echo "▸ vg_typecheck: skipped (VG_TYPECHECK_STRATEGY=skip)"; return 0 ;;
    full)       echo "▸ vg_typecheck: forced full mode"; vg_typecheck_incremental "$pkg"; return $? ;;
    bootstrap)  echo "▸ vg_typecheck: forced bootstrap"; vg_typecheck_bootstrap "$pkg"; return $? ;;
    narrow)     echo "▸ vg_typecheck: forced narrow mode"; vg_typecheck_narrow "$pkg" "$base_ref"; return $? ;;
    auto)       ;;  # fall through to decision tree
    *)          echo "⚠ unknown VG_TYPECHECK_STRATEGY='$forced' — using auto" ;;
  esac

  # Measure project size (+ React heuristic — TSX files balloon tsc memory ~3x)
  local ts_count tsx_count file_count
  ts_count=$(find "$path/src" -type f -name '*.ts' 2>/dev/null | wc -l | tr -d ' ')
  tsx_count=$(find "$path/src" -type f -name '*.tsx' 2>/dev/null | wc -l | tr -d ' ')
  # Weight TSX files 3x because JSX type inference is memory-heavy
  file_count=$(( ts_count + tsx_count * 3 ))

  local small_threshold="${VG_TYPECHECK_SMALL_THRESHOLD:-300}"
  local large_threshold="${VG_TYPECHECK_LARGE_THRESHOLD:-1200}"

  # Check OOM history (prune >7d, read rest)
  local oom_log="${path}/.tsbuildinfo-oom-log"
  local recent_oom=0
  if [ -f "$oom_log" ]; then
    local now
    now=$(date +%s)
    local cutoff=$((now - 604800))  # 7 days
    # Filter recent OOMs, rewrite log with only recent entries
    local recent_log
    recent_log=$(mktemp)
    while IFS= read -r line; do
      local ts
      ts=$(echo "$line" | cut -d' ' -f1)
      if [ -n "$ts" ] && [ "$ts" -ge "$cutoff" ] 2>/dev/null; then
        echo "$line" >> "$recent_log"
        recent_oom=$((recent_oom + 1))
      fi
    done < "$oom_log"
    mv "$recent_log" "$oom_log"
  fi

  # Cache-first decision tree:
  #   1. OOM history → narrow (skip all attempts, go direct)
  #   2. warm (cache exists) → incremental (fast path)
  #   3. cold + small (<300 weighted) → incremental (it's quick even cold)
  #   4. cold + medium/large → bootstrap first, then incremental
  #      └─ bootstrap fail → narrow fallback
  local mode
  local weighted="ts=${ts_count} tsx=${tsx_count} weighted=${file_count}"
  local cache_exists=0
  _vg_typecheck_cache_exists "$path" && cache_exists=1

  if [ "$recent_oom" -ge 1 ]; then
    mode="narrow"
    echo "▸ vg_typecheck_adaptive: ${pkg} has ${recent_oom} recent OOM(s) — narrow (${weighted})"
  elif [ "$cache_exists" = "1" ]; then
    mode="incremental"
    echo "▸ vg_typecheck_adaptive: ${pkg} warm (cache exists) — incremental (${weighted})"
  elif [ "$file_count" -lt "$small_threshold" ]; then
    mode="incremental"
    echo "▸ vg_typecheck_adaptive: ${pkg} cold+small (${weighted}) — incremental (fast even cold)"
  else
    # Cold + medium/large — attempt bootstrap before full check to avoid OOM
    echo "▸ vg_typecheck_adaptive: ${pkg} cold (${weighted}) — attempting cache bootstrap"
    if vg_typecheck_cache_bootstrap "$pkg"; then
      mode="incremental"
      echo "✓ Bootstrap succeeded → incremental warm"
    else
      mode="narrow"
      echo "▸ Bootstrap failed → narrow fallback"
      echo "  Options: install tsgo (npm i -g @typescript/native-preview)"
      echo "           OR refactor into tsc project references (M1 debt)"
    fi
  fi

  case "$mode" in
    incremental)
      vg_typecheck_incremental "$pkg"
      local rc=$?
      if [ $rc -eq 137 ] || [ $rc -eq 134 ]; then
        # OOM — record + fallback to narrow
        echo "$(date +%s) full-check OOM rc=$rc" >> "$oom_log"
        echo "⚠ Full check OOM — falling back to narrow mode"
        vg_typecheck_narrow "$pkg" "$base_ref"
        return $?
      fi
      return $rc
      ;;
    narrow)
      vg_typecheck_narrow "$pkg" "$base_ref"
      return $?
      ;;
  esac
}

# Summary helper — print cache state for all packages.
vg_typecheck_status() {
  echo "━━━ typecheck cache state ━━━"
  local configs
  configs=$(ls apps/*/tsconfig.json packages/*/tsconfig.json 2>/dev/null)
  for tsconfig in $configs; do
    [ ! -f "$tsconfig" ] && continue
    local dir
    dir=$(dirname "$tsconfig")
    local pkg
    pkg=$(basename "$dir")
    local cache="${dir}/.tsbuildinfo"
    if [ -f "$cache" ]; then
      local size
      size=$(du -h "$cache" 2>/dev/null | awk '{print $1}' || echo "?")
      local mtime_epoch
      mtime_epoch=$(stat -c %Y "$cache" 2>/dev/null || stat -f %m "$cache" 2>/dev/null || echo 0)
      local age=$(( $(date +%s) - mtime_epoch ))
      printf "  %-20s  cache %6s  age %5ds\n" "$pkg" "$size" "$age"
    else
      printf "  %-20s  cold (no cache)\n" "$pkg"
    fi
  done
}
