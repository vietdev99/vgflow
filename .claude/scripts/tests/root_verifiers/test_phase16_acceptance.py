"""
Phase 16 Wave 5 — E2E acceptance smoke for Task Fidelity Lock.

Verifies every Phase 16 deliverable shipped across waves 0-4 is wired
correctly. 8 acceptance dimensions:

  1. Validators (3) — task-schema, crossai-output, task-fidelity
  2. Helpers       — task_hasher.py exports + canonical normalization
  3. Parser        — extract_task_section_v2 + extract_all_tasks
  4. Build wire    — build.md persists .meta.json + wires task-fidelity audit
  5. Schema gate   — verify-task-schema.py mode behavior across formats
  6. Body cap      — vg_completeness_check Check E (D-03)
  7. R4 caps       — pre-executor-check.py applied_caps (D-04)
  8. Fidelity 3-way — verify-task-fidelity.py PASS/WARN/BLOCK behavior (D-06)

Run: python -m pytest scripts/tests/root_verifiers/test_phase16_acceptance.py -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATORS = REPO_ROOT / "scripts" / "validators"
SCRIPTS = REPO_ROOT / "scripts"
COMMANDS = REPO_ROOT / "commands" / "vg"
SHARED = COMMANDS / "_shared"
FIXTURES = REPO_ROOT / "fixtures" / "phase16"
TASK_HASHER = SCRIPTS / "lib" / "task_hasher.py"


# ─── 1. Validators ────────────────────────────────────────────────────────

PHASE16_VALIDATOR_IDS = ["task-schema", "crossai-output", "task-fidelity"]


class TestPhase16Validators:
    @pytest.fixture(scope="class")
    def registry_text(self):
        return (VALIDATORS / "registry.yaml").read_text(encoding="utf-8")

    @pytest.mark.parametrize("vid", PHASE16_VALIDATOR_IDS)
    def test_registry_entry_present(self, vid, registry_text):
        assert re.search(
            rf"^\s*-\s*id:\s*['\"]?{re.escape(vid)}['\"]?\s*$",
            registry_text, re.MULTILINE,
        ), f"registry.yaml missing {vid}"

    @pytest.mark.parametrize("vid", PHASE16_VALIDATOR_IDS)
    def test_validator_script_present(self, vid):
        path = VALIDATORS / f"verify-{vid}.py"
        assert path.exists(), f"missing: {path}"

    @pytest.mark.parametrize("vid", PHASE16_VALIDATOR_IDS)
    def test_validator_help_runs(self, vid):
        proc = subprocess.run(
            [sys.executable, str(VALIDATORS / f"verify-{vid}.py"), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0, (
            f"verify-{vid}.py --help failed: {proc.stderr}"
        )


# ─── 2. task_hasher helper ───────────────────────────────────────────────

class TestPhase16Helper:
    def test_task_hasher_present(self):
        assert TASK_HASHER.exists(), f"missing: {TASK_HASHER}"

    def test_task_hasher_module_imports(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("th", TASK_HASHER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "task_block_sha256"), "missing task_block_sha256"
        assert hasattr(mod, "stable_meta"), "missing stable_meta"


# ─── 3. Parser exports ────────────────────────────────────────────────────

class TestPhase16Parser:
    def test_extract_task_section_v2_present(self):
        text = (SCRIPTS / "pre-executor-check.py").read_text(encoding="utf-8")
        assert "def extract_task_section_v2(" in text, (
            "pre-executor-check.py missing extract_task_section_v2"
        )

    def test_extract_all_tasks_present(self):
        text = (SCRIPTS / "pre-executor-check.py").read_text(encoding="utf-8")
        assert "def extract_all_tasks(" in text, (
            "pre-executor-check.py missing extract_all_tasks"
        )


# ─── 4. Build wire (D-01 + D-06) ─────────────────────────────────────────

class TestPhase16BuildWire:
    @pytest.fixture(scope="class")
    def build_md(self):
        return (COMMANDS / "build.md").read_text(encoding="utf-8")

    def test_meta_sidecar_persist_wired(self, build_md):
        assert "PROMPT_META_PERSIST" in build_md, (
            "build.md must persist .meta.json sidecar (D-01)"
        )
        assert ".meta.json" in build_md
        assert "task_meta" in build_md, (
            "build.md must reference CONTEXT_JSON.task_meta"
        )

    def test_task_fidelity_audit_wired(self, build_md):
        assert "verify-task-fidelity.py" in build_md, (
            "build.md step 8d must invoke verify-task-fidelity.py (D-06)"
        )
        assert "D-06 task fidelity audit" in build_md, (
            "build.md must surface verdict line for D-06 audit"
        )

    def test_r4_reads_applied_caps(self, build_md):
        # build.md should read ctx.get('applied_caps') for R4 budget
        assert "ctx.get('applied_caps')" in build_md, (
            "build.md R4 must read CONTEXT_JSON.applied_caps (D-04)"
        )

    def test_executor_prompt_materializes_blueprint_context(self, build_md):
        assert "PROMPT_FULL_PERSIST" in build_md, (
            "build.md must persist full executor prompt evidence before spawn"
        )
        assert '${TASK_CONTEXT}' in build_md
        assert '${GOALS_CONTEXT}' in build_md
        assert '${UI_SPEC_CONTEXT}' in build_md
        assert '${DESIGN_CONTEXT}' in build_md
        assert '${WAVE_CONTEXT}' in build_md

        stale_pointers = [
            '@${TASKS_DIR}/task-${TASK_NUM}.md',
            '@${PHASE_DIR}/TEST-GOALS.md',
            '@${PHASE_DIR}/UI-SPEC.md',
            '@${PHASE_DIR}/wave-${N}-context.md',
            '@.claude/commands/vg/_shared/vg-executor-rules.md',
            '@${DESIGN_OUTPUT_DIR}',
        ]
        for pointer in stale_pointers:
            assert pointer not in build_md, (
                "executor prompt must receive resolved literal context, "
                f"not lazy-read pointer {pointer}"
            )


# ─── 5. Schema gate behavior (D-02) ──────────────────────────────────────

def _run_validator(script: Path, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=20, env=env,
        cwd=str(cwd),
    )


def _seed_phase(tmp_path: Path) -> Path:
    phase_dir = tmp_path / ".vg" / "phases" / "16-fix"
    phase_dir.mkdir(parents=True)
    return phase_dir


def _verdict(stdout: str) -> str:
    try:
        return json.loads(stdout).get("verdict", "?")
    except json.JSONDecodeError:
        return "PARSE_ERROR"


class TestPhase16SchemaGate:
    @pytest.mark.parametrize("fmt,mode,expected_rc,expected_verdict", [
        ("heading-format", "legacy",     0, "PASS"),
        ("heading-format", "structured", 1, "BLOCK"),
        ("heading-format", "both",       0, "WARN"),
        ("xml-format",     "legacy",     0, "PASS"),
        ("xml-format",     "structured", 0, "PASS"),
        ("xml-format",     "both",       0, "PASS"),
    ])
    def test_mode_x_format_matrix(self, tmp_path, fmt, mode, expected_rc, expected_verdict):
        phase = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / f"{fmt}.PLAN.md", phase / "PLAN.md")
        r = _run_validator(VALIDATORS / "verify-task-schema.py",
                           ["--phase", "16", "--mode", mode], tmp_path)
        assert r.returncode == expected_rc, (
            f"{fmt}/{mode}: expected rc={expected_rc} got {r.returncode}; stdout={r.stdout[:300]}"
        )
        assert _verdict(r.stdout) == expected_verdict


# ─── 6. Body cap Check E (D-03) ──────────────────────────────────────────

class TestPhase16BodyCap:
    def _run_completeness(self, phase_dir: Path) -> dict:
        # vg_completeness_check.py uses --phase-dir not --phase
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "vg_completeness_check.py"),
             "--phase-dir", str(phase_dir), "--json"],
            capture_output=True, text=True, timeout=15,
        )
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def test_long_task_default_blocks(self, tmp_path):
        phase = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / "long-task.PLAN.md", phase / "PLAN.md")
        (phase / "CONTEXT.md").write_text("## P16.D-01: dummy\n", encoding="utf-8")
        (phase / "SPECS.md").write_text("## In Scope\n- Dummy\n", encoding="utf-8")
        out = self._run_completeness(phase)
        e = out.get("check_e", {})
        assert e.get("status") == "BLOCK", f"expected BLOCK; got {e}"
        assert e.get("violations_count", 0) >= 1

    def test_long_task_enriched_passes(self, tmp_path):
        phase = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / "long-task.PLAN.md", phase / "PLAN.md")
        (phase / "CONTEXT.md").write_text(
            "---\ncross_ai_enriched: true\n---\n## P16.D-01: dummy\n",
            encoding="utf-8",
        )
        (phase / "SPECS.md").write_text("## In Scope\n- Dummy\n", encoding="utf-8")
        out = self._run_completeness(phase)
        e = out.get("check_e", {})
        assert e.get("status") == "PASS", f"enriched should PASS; got {e}"


# ─── 7. R4 conditional caps (D-04) ───────────────────────────────────────

class TestPhase16R4Caps:
    def _run_pec(self, tmp_path: Path, ctx_text: str) -> dict:
        phase_dir = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / "heading-format.PLAN.md", phase_dir / "PLAN.md")
        (phase_dir / "CONTEXT.md").write_text(ctx_text, encoding="utf-8")
        (tmp_path / "vg.config.md").write_text("# minimal\n", encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "pre-executor-check.py"),
             "--phase-dir", str(phase_dir),
             "--task-num", "1",
             "--config", str(tmp_path / "vg.config.md"),
             "--repo-root", str(tmp_path)],
            capture_output=True, text=True, timeout=15,
        )
        return json.loads(r.stdout)

    def test_default_mode_caps(self, tmp_path):
        out = self._run_pec(tmp_path, "## P16.D-01: dummy\n")
        assert out.get("budget_mode") == "default"
        assert out["applied_caps"]["task_context"] == 300
        assert out["hard_total_max"] == 2500

    def test_enriched_mode_caps(self, tmp_path):
        out = self._run_pec(tmp_path, "---\ncross_ai_enriched: true\n---\n## P16.D-01: dummy\n")
        assert out.get("budget_mode") == "enriched"
        assert out["applied_caps"]["task_context"] == 600
        assert out["hard_total_max"] == 4000


# ─── 8. Task fidelity audit 3-way (D-06) ─────────────────────────────────

class TestPhase16TaskFidelity:
    def _seed_pair(self, tmp_path: Path, body_truncate_pct: float = 0.0):
        """Seed phase + run pre-executor-check + persist meta+prompt with
        the requested truncate ratio."""
        phase_dir = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / "heading-format.PLAN.md", phase_dir / "PLAN.md")
        (tmp_path / "vg.config.md").write_text("# minimal\n", encoding="utf-8")

        # Pre-executor-check to get task_meta
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "pre-executor-check.py"),
             "--phase-dir", str(phase_dir),
             "--task-num", "1",
             "--config", str(tmp_path / "vg.config.md"),
             "--repo-root", str(tmp_path)],
            capture_output=True, text=True, timeout=15,
        )
        ctx = json.loads(r.stdout)
        body = ctx["task_context"]
        meta = ctx["task_meta"]
        meta["wave"] = "wave-1"

        # Persist
        prompt_dir = phase_dir / ".build" / "wave-1" / "executor-prompts"
        prompt_dir.mkdir(parents=True)
        if body_truncate_pct > 0:
            lines = body.splitlines()
            keep = max(1, int(len(lines) * (1 - body_truncate_pct)))
            body = "\n".join(lines[:keep])
        # Phase 16 hot-fix (v2.11.1): build.md step 8c writes *.body.md
        # (separate from *.uimap.md UI-MAP wrapper). Test now mirrors that
        # production layout instead of the legacy *.md (which was the
        # UI-MAP wrapper, never the task body — see cross-AI BLOCKers 1+2).
        (prompt_dir / "1.body.md").write_text(body, encoding="utf-8")
        (prompt_dir / "1.prompt.md").write_text(
            f"<task_context>\n{body}\n</task_context>\n",
            encoding="utf-8",
        )
        (prompt_dir / "1.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return phase_dir, prompt_dir

    def test_verbatim_passes(self, tmp_path):
        _, pd = self._seed_pair(tmp_path, body_truncate_pct=0.0)
        r = _run_validator(VALIDATORS / "verify-task-fidelity.py",
                           ["--phase", "16", "--prompts-dir", str(pd)], tmp_path)
        assert r.returncode == 0
        assert _verdict(r.stdout) == "PASS"

    def test_severe_truncation_blocks(self, tmp_path):
        _, pd = self._seed_pair(tmp_path, body_truncate_pct=0.7)  # keep 30%
        r = _run_validator(VALIDATORS / "verify-task-fidelity.py",
                           ["--phase", "16", "--prompts-dir", str(pd)], tmp_path)
        assert r.returncode == 1
        assert _verdict(r.stdout) == "BLOCK"

    def test_minor_truncation_blocks_by_hash(self, tmp_path):
        # Phase 16 hot-fix C4 (v2.11.1): hash compare is strict — ANY content
        # drift (including 5% loss) BLOCKs. Pre-hotfix the audit only checked
        # line-count shortfall, so 5% loss returned PASS (was below 10% WARN
        # threshold). Cross-AI BLOCKer 1: that line-count-only check let
        # same-line paraphrase slip through. Now small loss = hash mismatch
        # = BLOCK as content_paraphrase (since shortfall_pct < 30% threshold).
        _, pd = self._seed_pair(tmp_path, body_truncate_pct=0.05)  # 5% loss
        r = _run_validator(VALIDATORS / "verify-task-fidelity.py",
                           ["--phase", "16", "--prompts-dir", str(pd)], tmp_path)
        assert r.returncode == 1
        assert _verdict(r.stdout) == "BLOCK"

    def test_missing_full_prompt_blocks(self, tmp_path):
        _, pd = self._seed_pair(tmp_path, body_truncate_pct=0.0)
        (pd / "1.prompt.md").unlink()
        r = _run_validator(VALIDATORS / "verify-task-fidelity.py",
                           ["--phase", "16", "--prompts-dir", str(pd)], tmp_path)
        assert r.returncode == 1
        out = json.loads(r.stdout)
        assert out["verdict"] == "BLOCK"
        assert any(
            e.get("type") == "missing_file"
            and "full executor prompt" in e.get("message", "")
            for e in out.get("evidence", [])
        )

    def test_full_prompt_without_task_body_blocks(self, tmp_path):
        _, pd = self._seed_pair(tmp_path, body_truncate_pct=0.0)
        (pd / "1.prompt.md").write_text(
            "<task_context>\n@.vg/phases/16-fix/PLAN.md#task-1\n</task_context>\n",
            encoding="utf-8",
        )
        r = _run_validator(VALIDATORS / "verify-task-fidelity.py",
                           ["--phase", "16", "--prompts-dir", str(pd)], tmp_path)
        assert r.returncode == 1
        out = json.loads(r.stdout)
        assert out["verdict"] == "BLOCK"
        types = [e.get("type") for e in out.get("evidence", [])]
        assert "full_prompt_missing_task_body" in types


# ─── 9. Phase 16 hot-fix v2.11.1 — production-path regression tests ──────
#
# These tests exercise the actual /vg pipeline code paths the cross-AI
# review found to be silently broken pre-hotfix. Each test is named after
# the BLOCKer it guards against (B1..B6 from the cross-AI review).


class TestPhase16HotfixParaphraseGate:
    """B1 regression: hash compare must catch same-line-count paraphrase.

    Codex GPT-5.5 verified pre-hotfix that replacing every body line with
    "PARAPHRASED LINE N" at identical line count returned PASS (audit only
    compared line counts, not content hashes). After C4, hash mismatch is
    the primary signal — same-size rewrite must BLOCK as content_paraphrase.
    """

    def _seed_paraphrase(self, tmp_path: Path):
        phase_dir = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / "heading-format.PLAN.md", phase_dir / "PLAN.md")
        (tmp_path / "vg.config.md").write_text("# minimal\n", encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "pre-executor-check.py"),
             "--phase-dir", str(phase_dir), "--task-num", "1",
             "--config", str(tmp_path / "vg.config.md"),
             "--repo-root", str(tmp_path)],
            capture_output=True, text=True, timeout=15,
        )
        ctx = json.loads(r.stdout)
        body = ctx["task_context"]
        meta = ctx["task_meta"]
        meta["wave"] = "wave-1"

        # Replace every line with same-length paraphrase keeping the line
        # count identical (the exact attack Codex used).
        original_lines = body.splitlines()
        paraphrased = "\n".join(
            f"PARAPHRASED LINE {i + 1} (same line count, different content)"
            for i in range(len(original_lines))
        )

        prompt_dir = phase_dir / ".build" / "wave-1" / "executor-prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "1.body.md").write_text(paraphrased, encoding="utf-8")
        (prompt_dir / "1.prompt.md").write_text(
            f"<task_context>\n{paraphrased}\n</task_context>\n",
            encoding="utf-8",
        )
        (prompt_dir / "1.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return phase_dir, prompt_dir

    def test_same_line_paraphrase_blocks_as_content_paraphrase(self, tmp_path):
        _, pd = self._seed_paraphrase(tmp_path)
        r = _run_validator(VALIDATORS / "verify-task-fidelity.py",
                           ["--phase", "16", "--prompts-dir", str(pd)], tmp_path)
        assert r.returncode == 1, f"paraphrase MUST BLOCK; stdout={r.stdout[:400]}"
        out = json.loads(r.stdout)
        assert out["verdict"] == "BLOCK"
        types = [e.get("type") for e in out.get("evidence", [])]
        assert "content_paraphrase" in types, (
            f"expected content_paraphrase evidence; got {types}; "
            f"stdout={r.stdout[:400]}"
        )


class TestPhase16HotfixXmlMain:
    """B4 regression: pre-executor-check.py main() must extract XML task body.

    Codex GPT-5.5 verified pre-hotfix that XML PLANs returned the
    "Task N not found in PLAN files" sentinel via legacy v1 extract,
    while v2 (used only for meta) reported source_format=xml. Two
    extraction sources of truth → silent drift. C1 unified to v2.
    """

    def test_xml_format_main_returns_body_not_sentinel(self, tmp_path):
        phase_dir = _seed_phase(tmp_path)
        shutil.copy(FIXTURES / "plans" / "xml-format.PLAN.md", phase_dir / "PLAN.md")
        (tmp_path / "vg.config.md").write_text("# minimal\n", encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "pre-executor-check.py"),
             "--phase-dir", str(phase_dir), "--task-num", "1",
             "--config", str(tmp_path / "vg.config.md"),
             "--repo-root", str(tmp_path)],
            capture_output=True, text=True, timeout=15,
        )
        ctx = json.loads(r.stdout)
        body = ctx.get("task_context", "")
        assert "not found in PLAN files" not in body.lower(), (
            f"XML PLAN must return body, got sentinel. body[:200]={body[:200]!r}"
        )
        assert "create-site" in body.lower() or "sites.controller.ts" in body, (
            f"expected XML task 1 body content; got body[:200]={body[:200]!r}"
        )
        # Meta format must agree with what was extracted
        meta = ctx.get("task_meta", {})
        assert meta.get("source_format") == "xml", (
            f"meta source_format must be xml; got {meta.get('source_format')}"
        )


class TestPhase16HotfixCrossaiHeading:
    """B6 regression: verify-crossai-output diff parser must handle heading
    PLAN format. Codex verified pre-hotfix: 50-line prose addition to a
    ## Task N: heading-format PLAN returned silent PASS (parser only matched
    XML <task id="N">). C2 added heading_task_re branch.
    """

    def _make_diff_with_heading_prose_growth(self) -> str:
        # Synthesize a unified diff that adds 35 prose lines under ## Task 1:
        # in a heading-format PLAN, with NO <context-refs>. Should BLOCK.
        prose_lines = "\n".join(f"+Line {i} of new prose explaining design" for i in range(35))
        return (
            "diff --git a/PLAN.md b/PLAN.md\n"
            "--- a/PLAN.md\n"
            "+++ b/PLAN.md\n"
            "@@ -10,3 +10,38 @@\n"
            " ## Task 1: existing\n"
            " existing line\n"
            f"{prose_lines}\n"
        )

    def test_classify_diff_lines_handles_heading_format(self):
        # Direct unit test on the function (no subprocess, no git).
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "verify_crossai_output", VALIDATORS / "verify-crossai-output.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        diff = self._make_diff_with_heading_prose_growth()
        result = mod._classify_diff_lines_per_task(diff)
        # Task "1" should appear in result with ≥ 30 prose_added (the threshold)
        assert "1" in result, f"heading task scope not detected; result={result}"
        assert result["1"]["prose_added"] >= 30, (
            f"prose_added must reflect ≥30 lines; got {result['1']}"
        )
        assert result["1"]["context_refs_added"] == 0


class TestPhase16HotfixUnconditionalPersist:
    """B3 regression: build.md step 8c must persist body.md + meta.json
    UNCONDITIONALLY (not gated on UI conditional). Codex verified pre-hotfix
    that backend tasks (no UI subtree, no design context) got no meta.json
    → fidelity audit silent PASS → orchestrator could paraphrase backend
    task bodies freely. C3 split persist.
    """

    @pytest.fixture(scope="class")
    def build_md(self):
        return (COMMANDS / "build.md").read_text(encoding="utf-8")

    def test_body_persist_outside_ui_conditional(self, build_md):
        # Find the ${TASK_NUM}.body.md persist line and confirm it is NOT
        # inside the `if [ -n "$UI_MAP_SUBTREE_BLOCK" ] || [ -n "$DESIGN_CONTEXT" ]; then`
        # block. Heuristic: the body persist line must appear BEFORE that
        # conditional in the same step section.
        body_persist_idx = build_md.find('${TASK_NUM}.body.md')
        ui_cond_idx = build_md.find('if [ -n "$UI_MAP_SUBTREE_BLOCK" ] || [ -n "$DESIGN_CONTEXT" ]; then')
        assert body_persist_idx > 0, "body.md persist not found in build.md"
        assert ui_cond_idx > 0, "UI conditional not found in build.md"
        # body persist must be FIRST occurrence; UI conditional comes after
        assert body_persist_idx < ui_cond_idx, (
            "${TASK_NUM}.body.md persist must be unconditional (before UI conditional); "
            f"got body.md at {body_persist_idx}, UI cond at {ui_cond_idx}"
        )

    def test_meta_json_persist_unconditional(self, build_md):
        # Same check for .meta.json persist
        meta_persist_idx = build_md.find('${TASK_NUM}.meta.json')
        ui_cond_idx = build_md.find('if [ -n "$UI_MAP_SUBTREE_BLOCK" ] || [ -n "$DESIGN_CONTEXT" ]; then')
        assert meta_persist_idx > 0
        assert ui_cond_idx > 0
        assert meta_persist_idx < ui_cond_idx, (
            "${TASK_NUM}.meta.json persist must be unconditional; "
            "C3 hot-fix moved it outside the UI conditional"
        )

    def test_uimap_persist_still_gated(self, build_md):
        # The uimap.md wrapper SHOULD remain conditional (only UI tasks
        # need the UI-MAP+DESIGN-REF audit input). Search for the actual
        # variable assignment (unique) rather than the bare filename which
        # also appears in the surrounding documentation comment.
        uimap_assign_idx = build_md.find('PROMPT_UIMAP_PERSIST="${PROMPT_PERSIST_DIR}/${TASK_NUM}.uimap.md"')
        ui_cond_idx = build_md.find('if [ -n "$UI_MAP_SUBTREE_BLOCK" ] || [ -n "$DESIGN_CONTEXT" ]; then')
        assert uimap_assign_idx > 0, "PROMPT_UIMAP_PERSIST assignment not found"
        assert ui_cond_idx > 0
        assert uimap_assign_idx > ui_cond_idx, (
            "PROMPT_UIMAP_PERSIST assignment must be INSIDE UI conditional "
            "(uimap.md wrapper is for UI tasks only)"
        )


class TestPhase16HotfixWiring:
    """B5 regression: skill bodies + orchestrator dispatch must invoke
    verify-task-schema and verify-crossai-output. Pre-hotfix the validators
    were registered but never called from any /vg command. C5 wired skill
    bodies; C7 wired orchestrator COMMAND_VALIDATORS dict.
    """

    @pytest.fixture(scope="class")
    def blueprint_md(self):
        return (COMMANDS / "blueprint.md").read_text(encoding="utf-8")

    @pytest.fixture(scope="class")
    def scope_md(self):
        return (COMMANDS / "scope.md").read_text(encoding="utf-8")

    @pytest.fixture(scope="class")
    def orchestrator_text(self):
        return (SCRIPTS / "vg-orchestrator" / "__main__.py").read_text(encoding="utf-8")

    def test_blueprint_md_invokes_task_schema(self, blueprint_md):
        assert "verify-task-schema.py" in blueprint_md, (
            "blueprint.md skill body must invoke verify-task-schema.py "
            "(C5 hot-fix wired into 2d-3c)"
        )

    def test_blueprint_md_invokes_crossai_output(self, blueprint_md):
        assert "verify-crossai-output.py" in blueprint_md, (
            "blueprint.md skill body must invoke verify-crossai-output.py"
        )
        # Should be gated on --crossai flag (only fires after enrichment ran)
        assert re.search(r"ARGUMENTS.*=~.*--crossai", blueprint_md), (
            "verify-crossai-output invocation in blueprint.md must be "
            "gated on --crossai flag"
        )

    def test_scope_md_invokes_crossai_output(self, scope_md):
        assert "verify-crossai-output.py" in scope_md, (
            "scope.md skill body must invoke verify-crossai-output.py "
            "(C6 hot-fix)"
        )

    def test_orchestrator_dispatch_blueprint_includes_p16(self, orchestrator_text):
        # COMMAND_VALIDATORS["vg:blueprint"] must include both new validators
        # (defense-in-depth alongside the skill body invocations).
        assert '"verify-task-schema"' in orchestrator_text, (
            "COMMAND_VALIDATORS must include verify-task-schema for vg:blueprint"
        )
        assert '"verify-crossai-output"' in orchestrator_text, (
            "COMMAND_VALIDATORS must include verify-crossai-output for vg:blueprint"
        )

    def test_orchestrator_dispatch_scope_includes_crossai_output(self, orchestrator_text):
        # Confirm verify-crossai-output appears in the vg:scope list (after
        # verify-human-language-response per C7 placement).
        scope_section_idx = orchestrator_text.find('"vg:scope": [')
        assert scope_section_idx > 0, "vg:scope key not found in COMMAND_VALIDATORS"
        # Slice from vg:scope to next top-level dict key (or end of dict)
        scope_slice_end = orchestrator_text.find("}", scope_section_idx)
        scope_section = orchestrator_text[scope_section_idx:scope_slice_end]
        assert '"verify-crossai-output"' in scope_section, (
            "vg:scope COMMAND_VALIDATORS list must include verify-crossai-output"
        )
