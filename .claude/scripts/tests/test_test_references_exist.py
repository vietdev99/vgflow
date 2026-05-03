from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REFS_DIR = REPO_ROOT / "commands/vg/_shared/test"

# Per-ref line ceilings — slack over actual line counts to absorb minor edits.
# Actual counts as of R2 Task 13 commit:
#   preflight=317, deploy=143, runtime=318,
#   goal-verification/overview=233, goal-verification/delegation=346,
#   codegen/overview=279, codegen/delegation=469, codegen/deep-probe=205,
#   codegen/mobile-codegen=126, fix-loop=392,
#   regression-security=626, close=646.
# codegen/delegation is largest sub-500 file; documented exception for delegation
# pattern complexity (L1/L2 binding + console gate logic).
# regression-security and close are documented exceptions: each aggregates
# 4-5 combined phases (5e+5f+5g+5h+mobile and write_report+reflection+complete).
REFS = {
    "preflight.md":                    {"path": "preflight.md",                       "ceiling": 400},
    "deploy.md":                       {"path": "deploy.md",                          "ceiling": 250},
    "runtime.md":                      {"path": "runtime.md",                         "ceiling": 400},
    "goal-verification/overview.md":   {"path": "goal-verification/overview.md",      "ceiling": 350},
    "goal-verification/delegation.md": {"path": "goal-verification/delegation.md",    "ceiling": 450},
    "codegen/overview.md":             {"path": "codegen/overview.md",                "ceiling": 400},
    "codegen/delegation.md":           {"path": "codegen/delegation.md",              "ceiling": 550},
    "codegen/deep-probe.md":           {"path": "codegen/deep-probe.md",              "ceiling": 300},
    "codegen/mobile-codegen.md":       {"path": "codegen/mobile-codegen.md",          "ceiling": 250},
    "fix-loop.md":                     {"path": "fix-loop.md",                        "ceiling": 500},
    "regression-security.md":          {"path": "regression-security.md",             "ceiling": 800},  # 5e+5f+5g+5h+mobile = 626 lines
    "close.md":                        {"path": "close.md",                           "ceiling": 700},  # write_report+reflection+complete = 646 lines
}


def test_all_test_refs_present():
    for name, info in REFS.items():
        p = REFS_DIR / info["path"]
        ceiling = info["ceiling"]
        assert p.exists(), f"missing ref: {p}"
        assert p.stat().st_size > 100, f"ref {p} too small ({p.stat().st_size} bytes)"
        lines = p.read_text().splitlines()
        assert len(lines) <= ceiling, (
            f"ref {p} exceeds {ceiling} lines (got {len(lines)})"
        )
