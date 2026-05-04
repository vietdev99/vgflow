#!/usr/bin/env bash
# vg-load — unified loader for split blueprint artifacts.
#
# Blueprint generates 3-layer artifacts (per-task/endpoint/goal split + index +
# flat concat). Consumers (build/test/review/accept/roam) use this helper for
# partial loading instead of reading the full flat file — saves context budget.
#
# USAGE
#   vg-load --phase <N> --artifact <plan|contracts|goals|edge-cases|crud-surfaces|lens-walk|rcrurd-invariant> [<filter-flags>]
#
# ARTIFACTS + FILTERS
#   --artifact plan
#     --task NN         single task file (PLAN/task-NN.md)
#     --wave N          all tasks in wave N (parsed from PLAN/index.md)
#     --full            flat PLAN.md (legacy concat, all tasks)
#     --list            print task filenames only
#     --index           print PLAN/index.md only (slim TOC)
#
#   --artifact contracts
#     --endpoint <slug> single endpoint file (API-CONTRACTS/<slug>.md)
#     --resource <name> all endpoints for a resource (e.g., 'sites')
#     --full            flat API-CONTRACTS.md
#     --list            print endpoint filenames only
#     --index           print API-CONTRACTS/index.md only
#
#   --artifact goals
#     --goal G-NN       single goal file (TEST-GOALS/G-NN.md)
#     --priority <p>    all goals matching priority (critical|important|nice-to-have)
#     --decision <id>   all goals citing decision (e.g., P7.D-02)
#     --full            flat TEST-GOALS.md
#     --list            print goal filenames only
#     --index           print TEST-GOALS/index.md only
#
#   --artifact edge-cases (P1 v2.49+)
#     --goal G-NN       single per-goal edge-case file (EDGE-CASES/G-NN.md)
#     --priority <p>    all edge-case files containing variants matching priority
#     --full            flat EDGE-CASES.md
#     --list            print per-goal edge-case filenames only
#     --index           print EDGE-CASES/index.md only
#
#   --artifact crud-surfaces (Task 37 — Bug E)
#       --resource <name>    → CRUD-SURFACES/<name>.md (per-resource slice)
#       --full | --index | --list
#
#   --artifact lens-walk (Task 37 — Bug E)
#       --goal G-NN          → LENS-WALK/G-NN.md (per-goal lens seeds)
#       --full | --index | --list
#
#   --artifact rcrurd-invariant (Task 37 — Bug E)
#       --goal G-NN          → RCRURD-INVARIANTS/G-NN.yaml (per-goal invariant)
#       --index | --list
#
# OPTIONAL
#   --phases-dir DIR    override default .vg/phases (or $PHASES_DIR env)
#   --quiet             suppress informational stderr
#
# EXAMPLES
#   vg-load --phase 7 --artifact plan --task 04
#   vg-load --phase 7 --artifact plan --wave 2
#   vg-load --phase 7 --artifact contracts --endpoint post-api-sites
#   vg-load --phase 7 --artifact goals --priority critical
#
# EXIT CODES
#   0  ok
#   1  bad args
#   2  artifact dir / file not found
#   3  filter matched zero files

set -euo pipefail

phase=""
artifact=""
filter_kind=""
filter_value=""
phases_dir="${PHASES_DIR:-.vg/phases}"
quiet=0

while [ $# -gt 0 ]; do
  case "$1" in
    --phase)        phase="$2"; shift 2 ;;
    --artifact)     artifact="$2"; shift 2 ;;
    --task|--wave|--endpoint|--resource|--goal|--priority|--decision)
                    filter_kind="${1#--}"; filter_value="$2"; shift 2 ;;
    --full|--list|--index)
                    filter_kind="${1#--}"; filter_value=""; shift ;;
    --phases-dir)   phases_dir="$2"; shift 2 ;;
    --quiet)        quiet=1; shift ;;
    -h|--help)      sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; /^set -euo/d'; exit 0 ;;
    *)              echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

[ -z "$phase" ]    && { echo "ERROR: --phase required" >&2; exit 1; }
[ -z "$artifact" ] && { echo "ERROR: --artifact required" >&2; exit 1; }

# Validate artifact name before filter check so unknown artifacts produce the right error.
case "$artifact" in
  plan|contracts|goals|edge-cases|crud-surfaces|lens-walk|rcrurd-invariant) ;;
  *) echo "ERROR: unknown artifact '$artifact'. Supported: plan, contracts, goals, edge-cases, crud-surfaces, lens-walk, rcrurd-invariant" >&2; exit 1 ;;
esac

[ -z "$filter_kind" ] && { echo "ERROR: filter required (--task/--wave/--full/--list/--index/etc.)" >&2; exit 1; }

# Resolve phase_dir — accept "7", "7.14", "01-foo", or full path.
phase_dir=""
if [ -d "$phase" ]; then
  phase_dir="$phase"
elif [ -d "${phases_dir}/${phase}" ]; then
  phase_dir="${phases_dir}/${phase}"
else
  # Try glob match: phases_dir/<NN>-* or phases_dir/<phase>*
  match=$(find "$phases_dir" -maxdepth 1 -type d -name "${phase}*" 2>/dev/null | head -1)
  if [ -n "$match" ]; then
    phase_dir="$match"
  fi
fi

[ -z "$phase_dir" ] || [ ! -d "$phase_dir" ] && {
  echo "ERROR: phase dir not found for '$phase' (searched $phases_dir)" >&2
  exit 2
}

[ "$quiet" = "0" ] && echo "▸ vg-load phase=$phase_dir artifact=$artifact filter=$filter_kind=$filter_value" >&2

case "$artifact" in
  plan)
    sub_dir="$phase_dir/PLAN"
    flat_file="$phase_dir/PLAN.md"
    case "$filter_kind" in
      full)  cat "$flat_file" ;;
      index) cat "$sub_dir/index.md" ;;
      list)  ls "$sub_dir"/task-*.md 2>/dev/null || { echo "no task files found in $sub_dir" >&2; exit 3; } ;;
      task)
        # Pad to 2 digits
        nn=$(printf "%02d" "${filter_value#0}" 2>/dev/null || echo "$filter_value")
        f="$sub_dir/task-${nn}.md"
        [ -f "$f" ] || { echo "ERROR: task file not found: $f" >&2; exit 2; }
        cat "$f"
        ;;
      wave)
        # Parse wave map from PLAN/index.md: lines like "Wave 2 (after 1): tasks 03, 04, 05"
        index="$sub_dir/index.md"
        [ -f "$index" ] || { echo "ERROR: index missing: $index" >&2; exit 2; }
        task_ids=$(grep -E "^- Wave ${filter_value} " "$index" 2>/dev/null \
                   | grep -oE '[0-9]+' | tail -n +2 | sort -u)
        [ -z "$task_ids" ] && { echo "ERROR: no tasks found for wave $filter_value" >&2; exit 3; }
        for t in $task_ids; do
          nn=$(printf "%02d" "$t")
          f="$sub_dir/task-${nn}.md"
          [ -f "$f" ] && cat "$f" && echo ""
        done
        ;;
      *) echo "ERROR: unsupported filter '$filter_kind' for plan" >&2; exit 1 ;;
    esac
    ;;

  contracts)
    sub_dir="$phase_dir/API-CONTRACTS"
    flat_file="$phase_dir/API-CONTRACTS.md"
    case "$filter_kind" in
      full)  cat "$flat_file" ;;
      index) cat "$sub_dir/index.md" ;;
      list)  ls "$sub_dir"/*.md 2>/dev/null | grep -v '/index\.md$' || { echo "no endpoint files" >&2; exit 3; } ;;
      endpoint)
        f="$sub_dir/${filter_value}.md"
        [ -f "$f" ] || { echo "ERROR: endpoint file not found: $f" >&2; exit 2; }
        cat "$f"
        ;;
      resource)
        # Match files containing resource name (e.g., 'sites' → post-api-sites.md, get-api-sites-id.md)
        files=$(ls "$sub_dir"/*.md 2>/dev/null | grep -E "/-?[a-z]+-${filter_value}(-|\.)" || true)
        [ -z "$files" ] && { echo "ERROR: no endpoints for resource '$filter_value'" >&2; exit 3; }
        for f in $files; do
          cat "$f" && echo ""
        done
        ;;
      *) echo "ERROR: unsupported filter '$filter_kind' for contracts" >&2; exit 1 ;;
    esac
    ;;

  goals)
    sub_dir="$phase_dir/TEST-GOALS"
    flat_file="$phase_dir/TEST-GOALS.md"
    case "$filter_kind" in
      full)  cat "$flat_file" ;;
      index) cat "$sub_dir/index.md" ;;
      list)  ls "$sub_dir"/G-*.md 2>/dev/null || { echo "no goal files" >&2; exit 3; } ;;
      goal)
        f="$sub_dir/${filter_value}.md"
        [ -f "$f" ] || { echo "ERROR: goal file not found: $f" >&2; exit 2; }
        cat "$f"
        ;;
      priority)
        files=$(grep -lE "^\*\*Priority:\*\*\s*${filter_value}\b" "$sub_dir"/G-*.md 2>/dev/null || true)
        [ -z "$files" ] && { echo "ERROR: no goals with priority '$filter_value'" >&2; exit 3; }
        for f in $files; do
          cat "$f" && echo ""
        done
        ;;
      decision)
        # Match goals citing decision (e.g., 'P7.D-02' in title or **Decisions:**)
        files=$(grep -lE "${filter_value}\b" "$sub_dir"/G-*.md 2>/dev/null || true)
        [ -z "$files" ] && { echo "ERROR: no goals citing decision '$filter_value'" >&2; exit 3; }
        for f in $files; do
          cat "$f" && echo ""
        done
        ;;
      *) echo "ERROR: unsupported filter '$filter_kind' for goals" >&2; exit 1 ;;
    esac
    ;;

  edge-cases)
    # P1 v2.49+: edge cases artifact (3-layer split mirrors goals).
    # Layer 3: EDGE-CASES.md (flat). Layer 2: EDGE-CASES/index.md (TOC).
    # Layer 1: EDGE-CASES/G-NN.md (per-goal, primary for build/review/test).
    sub_dir="$phase_dir/EDGE-CASES"
    flat_file="$phase_dir/EDGE-CASES.md"
    case "$filter_kind" in
      full)  cat "$flat_file" 2>/dev/null || { echo "ERROR: $flat_file not found" >&2; exit 2; } ;;
      index) cat "$sub_dir/index.md" 2>/dev/null || { echo "ERROR: $sub_dir/index.md not found" >&2; exit 2; } ;;
      list)  ls "$sub_dir"/G-*.md 2>/dev/null || { echo "no edge-case files" >&2; exit 3; } ;;
      goal)
        f="$sub_dir/${filter_value}.md"
        [ -f "$f" ] || { echo "ERROR: edge-case file not found: $f" >&2; exit 2; }
        cat "$f"
        ;;
      priority)
        # Match files with variant rows containing priority cell
        files=$(grep -lE "\| ${filter_value} \|" "$sub_dir"/G-*.md 2>/dev/null || true)
        [ -z "$files" ] && { echo "ERROR: no edge-cases with priority '$filter_value'" >&2; exit 3; }
        for f in $files; do
          cat "$f" && echo ""
        done
        ;;
      *) echo "ERROR: unsupported filter '$filter_kind' for edge-cases (use --goal G-NN, --priority, --full, --index, --list)" >&2; exit 1 ;;
    esac
    ;;

  crud-surfaces)
    # Task 37 (Bug E) — per-resource slicing for build envelope.
    sub_dir="$phase_dir/CRUD-SURFACES"
    flat_file="$phase_dir/CRUD-SURFACES.md"
    case "$filter_kind" in
      full)  cat "$flat_file" 2>/dev/null || { echo "ERROR: $flat_file not found" >&2; exit 2; } ;;
      index) cat "$sub_dir/index.md" 2>/dev/null || { echo "ERROR: $sub_dir/index.md not found" >&2; exit 2; } ;;
      list)  ls "$sub_dir"/*.md 2>/dev/null | grep -v '/index\.md$' || { echo "no resource files" >&2; exit 3; } ;;
      resource)
        f="$sub_dir/${filter_value}.md"
        [ -f "$f" ] || { echo "ERROR: resource file not found: $f" >&2; exit 2; }
        cat "$f"
        ;;
      *) echo "ERROR: unsupported filter '$filter_kind' for crud-surfaces (use --resource <name>, --full, --index, --list)" >&2; exit 1 ;;
    esac
    ;;

  lens-walk)
    # Task 37 — per-goal slicing for build envelope (consumes blueprint 2b5e_a_lens_walk output).
    sub_dir="$phase_dir/LENS-WALK"
    flat_file="$phase_dir/LENS-WALK.md"
    case "$filter_kind" in
      full)  cat "$flat_file" 2>/dev/null || { echo "ERROR: $flat_file not found" >&2; exit 2; } ;;
      index) cat "$sub_dir/index.md" 2>/dev/null || { echo "ERROR: $sub_dir/index.md not found" >&2; exit 2; } ;;
      list)  ls "$sub_dir"/G-*.md 2>/dev/null || { echo "no lens-walk goal files" >&2; exit 3; } ;;
      goal)
        f="$sub_dir/${filter_value}.md"
        [ -f "$f" ] || { echo "ERROR: lens-walk file not found: $f" >&2; exit 2; }
        cat "$f"
        ;;
      *) echo "ERROR: unsupported filter '$filter_kind' for lens-walk (use --goal G-NN, --full, --index, --list)" >&2; exit 1 ;;
    esac
    ;;

  rcrurd-invariant)
    # Task 37 — per-goal RCRURD/RCRURDR invariants (Task 22 schema, extended Task 39).
    sub_dir="$phase_dir/RCRURD-INVARIANTS"
    case "$filter_kind" in
      index) cat "$sub_dir/index.md" 2>/dev/null || { echo "ERROR: $sub_dir/index.md not found" >&2; exit 2; } ;;
      list)  ls "$sub_dir"/G-*.yaml 2>/dev/null || { echo "no rcrurd files" >&2; exit 3; } ;;
      goal)
        f="$sub_dir/${filter_value}.yaml"
        [ -f "$f" ] || { echo "ERROR: rcrurd file not found: $f" >&2; exit 2; }
        cat "$f"
        ;;
      *) echo "ERROR: unsupported filter '$filter_kind' for rcrurd-invariant (use --goal G-NN, --index, --list)" >&2; exit 1 ;;
    esac
    ;;

  *)
    echo "ERROR: unknown artifact '$artifact'. Supported: plan, contracts, goals, edge-cases, crud-surfaces, lens-walk, rcrurd-invariant" >&2
    exit 1
    ;;
esac
