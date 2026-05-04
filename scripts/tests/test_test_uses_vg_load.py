"""Static check: vg:test pipeline uses vg-load instead of flat
PLAN.md / API-CONTRACTS.md / TEST-GOALS.md reads in AI-context paths.

Phase F Task 30 absorption — mirrors test_accept_uses_vg_load.py convention.

Positive assertions (vg-load MUST appear):
  - commands/vg/_shared/test/runtime.md           (5b contract enumeration)
  - commands/vg/_shared/test/goal-verification/delegation.md  (goal loading)
  - commands/vg/_shared/test/codegen/delegation.md (goals + contracts)
  - agents/vg-test-codegen/SKILL.md               (subagent: codegen)
  - agents/vg-test-goal-verifier/SKILL.md         (subagent: goal verifier)

Note on fix-loop.md: Task 8 implementer found no flat reads of
PLAN/API-CONTRACTS/TEST-GOALS in fix-loop.md requiring injection (the file's
`cat` references are for REVIEW-FEEDBACK.md and GOAL-COVERAGE-MATRIX.md in
user-guidance display blocks — those are small, non-AI-context artifacts
outside the forbidden list). vg-load is therefore NOT asserted for fix-loop.md;
only the negative assertion (no forbidden flat cats) applies.

Negative assertions (forbidden patterns MUST NOT appear in AI-context paths):
  - cat ${PHASE_DIR}/PLAN.md
  - cat ${PHASE_DIR}/API-CONTRACTS.md
  - cat ${PHASE_DIR}/TEST-GOALS.md
  The FLAT_PATTERN regex only catches shell `cat` invocations and
  `Read <artifact>.md` tool calls — NOT Python `read_text()` calls followed
  by parse operations (BFS, regex, json.load — those are KEEP-FLAT data ops).
"""
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]

# AI-context paths with positive vg-load assertion required
RUNTIME_MD     = REPO / "commands/vg/_shared/test/runtime.md"
GV_DELEGATION  = REPO / "commands/vg/_shared/test/goal-verification/delegation.md"
CG_DELEGATION  = REPO / "commands/vg/_shared/test/codegen/delegation.md"
FIX_LOOP_MD    = REPO / "commands/vg/_shared/test/fix-loop.md"
TEST_ENTRY     = REPO / "commands/vg/test.md"
SHARED_TEST_DIR = REPO / "commands/vg/_shared/test"

# Subagent SKILL.md files
CODEGEN_SKILL  = REPO / "agents/vg-test-codegen/SKILL.md"
GV_SKILL       = REPO / "agents/vg-test-goal-verifier/SKILL.md"

# Regex: shell cat of forbidden artifacts, or Read tool invocation of them.
# Deliberately excludes:
#   - Python read_text() / open() used for data parsing (BFS, regex, json.load)
#   - Python / shell comments (lines where the first non-whitespace char is #)
#   - Markdown description prose containing "Read TEST-GOALS.md" as narrative
# Only catches active shell `cat` and top-level `Read <artifact>.md` tool calls.
FLAT_PATTERN = re.compile(
    r"(cat\s+[\"']?\$\{?(?:PHASE_DIR|PLANNING_DIR)[^}]*\}?[/\"']?(?:PLAN|API-CONTRACTS|TEST-GOALS)\.md"
    r"|(?<![#\w])Read\s+\S*(?:PLAN|API-CONTRACTS|TEST-GOALS)\.md)"
)

_COMMENT_LINE = re.compile(r"^\s*#")


def _flat_reads(path: Path):
    """Yield (line_no, snippet) for forbidden flat reads found in path.

    Skips lines that are pure comments (first non-whitespace char is #) to
    avoid flagging Python / shell comment lines such as:
      # 1. Read TEST-GOALS.md — priority per goal
    which are documentation / KEEP-FLAT annotations, not active flat reads.
    """
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if _COMMENT_LINE.match(line):
            continue
        if FLAT_PATTERN.search(line):
            yield i, line.strip()


# ---------------------------------------------------------------------------
# Positive assertions — vg-load MUST be referenced
# ---------------------------------------------------------------------------

def test_test_runtime_uses_vg_load():
    """runtime.md MUST use vg-load for 5b contract enumeration."""
    body = RUNTIME_MD.read_text(encoding="utf-8")
    assert "vg-load" in body, (
        f"{RUNTIME_MD.relative_to(REPO)} must reference vg-load "
        "(Phase F Task 30 — 5b uses vg-load --artifact contracts --index)"
    )


def test_test_goal_verification_uses_vg_load():
    """goal-verification/delegation.md MUST use vg-load for goal loading."""
    body = GV_DELEGATION.read_text(encoding="utf-8")
    assert "vg-load" in body, (
        f"{GV_DELEGATION.relative_to(REPO)} must reference vg-load "
        "(goals MUST be loaded via vg-load --priority, not cat TEST-GOALS.md flat)"
    )


def test_test_codegen_uses_vg_load():
    """codegen/delegation.md MUST use vg-load for goals + contracts."""
    body = CG_DELEGATION.read_text(encoding="utf-8")
    assert "vg-load" in body, (
        f"{CG_DELEGATION.relative_to(REPO)} must reference vg-load "
        "(goals + per-endpoint contracts via vg-load — Phase F Task 30)"
    )
    # Must cover both goals and contracts loads
    assert re.search(r"vg-load.*artifact\s+goals", body), (
        f"{CG_DELEGATION.relative_to(REPO)} must use vg-load --artifact goals"
    )
    assert re.search(r"vg-load.*artifact\s+contracts", body), (
        f"{CG_DELEGATION.relative_to(REPO)} must use vg-load --artifact contracts"
    )


def test_test_md_uses_vg_load_for_artifact_loads():
    """vg-load must be referenced somewhere in the test pipeline
    (entry OR _shared/test/ refs — slim entry may delegate to refs)."""
    found_entry = "vg-load" in TEST_ENTRY.read_text(encoding="utf-8")
    found_refs = any(
        "vg-load" in p.read_text(encoding="utf-8")
        for p in SHARED_TEST_DIR.rglob("*.md")
    )
    assert found_entry or found_refs, (
        "Neither test.md entry nor any _shared/test/**/*.md ref references "
        "vg-load — at least one ref must use vg-load (Phase F Task 30)"
    )


# ---------------------------------------------------------------------------
# fix-loop.md: no vg-load required (KEEP-FLAT — see module docstring)
# but forbidden cats MUST still be absent
# ---------------------------------------------------------------------------

def test_test_fix_loop_no_forbidden_flat_cats():
    """fix-loop.md must not cat PLAN/API-CONTRACTS/TEST-GOALS flat.

    vg-load is NOT required here: the file's only `cat` invocations are for
    REVIEW-FEEDBACK.md and GOAL-COVERAGE-MATRIX.md in user-guidance display
    blocks (small, non-AI-context artifacts outside the forbidden list).
    Task 8 found no flat reads needing injection, so no positive assertion.
    """
    failures = list(_flat_reads(FIX_LOOP_MD))
    assert not failures, (
        f"{FIX_LOOP_MD.relative_to(REPO)} contains forbidden flat reads:\n"
        + "\n".join(f"  line {n}: {s}" for n, s in failures)
    )


# ---------------------------------------------------------------------------
# Negative assertion — no flat artifact cats across all AI-context paths
# ---------------------------------------------------------------------------

def test_test_no_flat_artifact_cats_in_ai_context_paths():
    """All _shared/test/**/*.md refs + entry MUST NOT cat
    PLAN.md / API-CONTRACTS.md / TEST-GOALS.md for AI context.

    Python read_text() calls used for deterministic data-parsing operations
    (BFS, regex, json.load — e.g. chain-count computation in runtime.md) are
    explicitly excluded by the FLAT_PATTERN regex (it only catches shell `cat`
    and `Read <artifact>.md` tool patterns)."""
    failures = []
    targets = [TEST_ENTRY, *sorted(SHARED_TEST_DIR.rglob("*.md"))]
    for path in targets:
        for n, snippet in _flat_reads(path):
            failures.append(f"  {path.relative_to(REPO)}:{n}: {snippet}")
    assert not failures, (
        "Forbidden flat reads of PLAN/API-CONTRACTS/TEST-GOALS detected "
        "(Phase F Task 30 — use vg-load instead):\n" + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# Subagent SKILL.md assertions
# ---------------------------------------------------------------------------

def test_test_subagents_forbid_flat_artifact_cat():
    """Both subagent SKILLs MUST contain a 'no cat flat' prohibition.

    Checks that vg-test-codegen and vg-test-goal-verifier declare, in their
    HARD-GATE / Forbidden section, that direct cat of PLAN.md / API-CONTRACTS.md
    / TEST-GOALS.md is prohibited."""
    for skill_path in (CODEGEN_SKILL, GV_SKILL):
        assert skill_path.exists(), f"missing subagent SKILL: {skill_path}"
        body = skill_path.read_text(encoding="utf-8")
        # Each skill must mention vg-load
        assert "vg-load" in body, (
            f"{skill_path.relative_to(REPO)} must reference vg-load"
        )
        # Each skill must forbid cat of TEST-GOALS.md (or flat reads in general)
        has_flat_prohibition = bool(
            re.search(r"MUST NOT cat.*(?:TEST-GOALS|PLAN|API-CONTRACTS)", body)
            or re.search(r"cat.*(?:TEST-GOALS|PLAN|API-CONTRACTS).*flat", body)
            or re.search(r"no cat.*flat", body, re.IGNORECASE)
        )
        assert has_flat_prohibition, (
            f"{skill_path.relative_to(REPO)} must explicitly forbid "
            "`cat <artifact>.md` flat reads (add to HARD-GATE or Forbidden section)"
        )
