"""
Phase 17 polish — pre-executor-check.py extraction-bug regression tests.

Self-audit during P17 cross-AI review found 2 silent-truncation bugs in
the extractors that pipe TEST-GOALS / API-CONTRACTS into executor prompts:

  1. extract_contract_section: matched on LAST PATH SEGMENT only →
     /api/v1/sites and /api/v2/sites collide → first-match-wins → wrong
     contract version reaches the executor.

  2. extract_goals_context: when the requested goal is LAST in
     TEST-GOALS.md (no next ## Goal G-XX heading found), code truncated
     to 30 lines. Phase 15 D-16 goals routinely have 50-100+ lines
     (interactive_controls + persistence check + criteria). Last goal
     silently arrived incomplete to executor.

Both fixes verified here so future drift can't reintroduce the bugs.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PEC_PATH = REPO_ROOT / "scripts" / "pre-executor-check.py"


def _load_pre_executor_check():
    spec = importlib.util.spec_from_file_location("pre_executor_check", PEC_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pec():
    return _load_pre_executor_check()


# ─── Bug fix 1: extract_contract_section full-path disambiguation ────────

API_CONTRACTS_V1_V2_COLLISION = """\
# API Contracts

### POST /api/v1/sites

Block 1: legacy v1 auth
```typescript
export const v1Auth = [requireAuth(), legacyMiddleware()];
```

### POST /api/v2/sites

Block 1: NEW v2 auth (this is what executor SHOULD get for v2 tasks)
```typescript
export const v2Auth = [requireAuth(), v2Middleware(), rateLimit(60)];
```

### GET /api/v2/sites

Block 1: list endpoint
```typescript
export const listSitesAuth = [requireAuth()];
```
"""


class TestContractFullPathMatch:
    def test_v2_endpoint_does_not_collide_with_v1(self, tmp_path, pec):
        (tmp_path / "API-CONTRACTS.md").write_text(
            API_CONTRACTS_V1_V2_COLLISION, encoding="utf-8"
        )
        # Task touches v2 — should get v2Auth, NOT v1Auth
        task_text = "<edits-endpoint>POST /api/v2/sites</edits-endpoint>"
        result = pec.extract_contract_section(tmp_path, task_text)
        assert "v2Auth" in result, (
            "extract_contract_section returned wrong version — v1 leaked into v2 task"
        )
        assert "legacyMiddleware" not in result, (
            "v1 contract content (legacyMiddleware) leaked into v2 task"
        )

    def test_v1_endpoint_does_not_collide_with_v2(self, tmp_path, pec):
        (tmp_path / "API-CONTRACTS.md").write_text(
            API_CONTRACTS_V1_V2_COLLISION, encoding="utf-8"
        )
        # Task touches v1 — should get v1Auth, NOT v2Auth
        task_text = "<edits-endpoint>POST /api/v1/sites</edits-endpoint>"
        result = pec.extract_contract_section(tmp_path, task_text)
        assert "legacyMiddleware" in result, (
            "extract_contract_section missed v1 contract — full-path match broke"
        )
        assert "v2Middleware" not in result, (
            "v2 contract content leaked into v1 task — full-path disambiguation failed"
        )


# ─── Bug fix 2: extract_goals_context no-30-line-cap on last goal ────────

TEST_GOALS_LAST_GOAL_LONG = """\
# Test Goals

## Goal G-01: Quick goal
Brief content.

## Goal G-99: Long last goal
**Priority:** critical
**Success criteria:**
- Line 1
- Line 2
- Line 3
- Line 4
- Line 5
- Line 6
- Line 7
- Line 8
- Line 9
- Line 10
- Line 11
- Line 12
- Line 13
- Line 14
- Line 15
- Line 16
- Line 17
- Line 18
- Line 19
- Line 20
- Line 21
- Line 22
- Line 23
- Line 24
- Line 25
- Line 26
- Line 27
- Line 28
- Line 29
- Line 30
**Persistence check:**
- Pre-submit: read role
- Action: edit role
- Post-submit wait: API 200
- Refresh: page.reload()
- Re-read: re-open modal
- Assert: role = new value AND != pre value
**interactive_controls:**
  url_sync: true
  filters:
    - name: status
      values: [active, paused, archived]
"""


class TestGoalsContextNoTruncation:
    def test_last_goal_full_body_returned(self, tmp_path, pec):
        (tmp_path / "TEST-GOALS.md").write_text(
            TEST_GOALS_LAST_GOAL_LONG, encoding="utf-8"
        )
        task_text = "<goals-covered>[G-99]</goals-covered>"
        result = pec.extract_goals_context(tmp_path, task_text)
        # Old behavior: truncated to 30 lines from "## Goal G-99" — would
        # cut off persistence check + interactive_controls. Verify both
        # sections survive.
        assert "**Persistence check:**" in result, (
            "Persistence check truncated — extract_goals_context still capping at 30 lines"
        )
        assert "**interactive_controls:**" in result, (
            "interactive_controls block truncated — Phase 15 D-16 dependency lost"
        )
        assert "Line 30" in result, "Mid-body content truncated"

    def test_non_last_goal_still_terminates_at_next_heading(self, tmp_path, pec):
        # G-01 is followed by ## Goal G-99 → must stop at next heading
        (tmp_path / "TEST-GOALS.md").write_text(
            TEST_GOALS_LAST_GOAL_LONG, encoding="utf-8"
        )
        task_text = "<goals-covered>[G-01]</goals-covered>"
        result = pec.extract_goals_context(tmp_path, task_text)
        assert "Brief content" in result, "G-01 body missing"
        # Critical: must NOT bleed into G-99
        assert "Long last goal" not in result, (
            "extract_goals_context bled past next-goal heading"
        )
        assert "Persistence check" not in result, (
            "G-99 content leaked into G-01 extraction"
        )
