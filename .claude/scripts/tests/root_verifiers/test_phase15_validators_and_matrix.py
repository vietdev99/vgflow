"""
Phase 15 Wave 8 — validator + matrix smoke tests.

Covers:
  - verify-uimap-schema.py (D-15) on valid + invalid fixtures.
  - verify-uat-narrative-fields.py (D-05/06/07) on inline narrative samples.
  - verify-uat-strings-no-hardcode.py (D-18) on inline narrative samples.
  - verify-filter-test-coverage.py (D-16) against a sample generated spec
    bundle (matches the D-16 13/18 source-block thresholds).
  - filter-test-matrix.mjs renderer + enumerator (Phase 15 T6.1).
  - extract-subtree-haiku.mjs subtree filter (Phase 15 T4.2).

Tests reference the LOCAL vgflow-repo source tree so they are runnable
during workflow development. Each validator gets the `VG_REPO_ROOT`
env var pointing at a tmp_path with `.vg/phases/<id>-fixture/` populated
with the artifacts under test — this is the contract `find_phase_dir`
expects (scripts/validators/_common.py).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "fixtures" / "phase15"
VALIDATORS = REPO_ROOT / "scripts" / "validators"
SCRIPTS = REPO_ROOT / "scripts"
SHARED = REPO_ROOT / "commands" / "vg" / "_shared"


def _run_validator(script: Path, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=20, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _seed_phase_dir(tmp_path: Path, phase_id: str = "15") -> Path:
    """Create tmp_path/.vg/phases/{phase_id}-fixture/ and return that dir."""
    phase_dir = tmp_path / ".vg" / "phases" / f"{phase_id}-fixture"
    phase_dir.mkdir(parents=True, exist_ok=True)
    return phase_dir


def _verdict(stdout: str) -> str:
    try:
        return json.loads(stdout).get("verdict", "?")
    except json.JSONDecodeError:
        return f"NON-JSON: {stdout[:120]}"


# ─── D-15 verify-uimap-schema.py ──────────────────────────────────────────

class TestUimapSchema:
    def test_valid_fixture_passes(self, tmp_path):
        phase = _seed_phase_dir(tmp_path)
        shutil.copy(FIXTURES / "uimap" / "valid.md", phase / "UI-MAP.md")
        r = _run_validator(VALIDATORS / "verify-uimap-schema.py", ["--phase", "15"], tmp_path)
        assert r.returncode == 0, f"valid UI-MAP should PASS — stdout={r.stdout} stderr={r.stderr}"
        assert _verdict(r.stdout) in ("PASS", "WARN")

    def test_missing_required_fields_blocks(self, tmp_path):
        phase = _seed_phase_dir(tmp_path)
        shutil.copy(FIXTURES / "uimap" / "invalid-missing-fields.md", phase / "UI-MAP.md")
        r = _run_validator(VALIDATORS / "verify-uimap-schema.py", ["--phase", "15"], tmp_path)
        assert r.returncode == 1, f"invalid UI-MAP should BLOCK — got rc={r.returncode}"
        assert _verdict(r.stdout) == "BLOCK"


# ─── D-05/06/07 verify-uat-narrative-fields.py ────────────────────────────

VALID_NARRATIVE = """## G-01: Login flow

Truy cập: `/admin/login` (Vai trò: `admin`, Tài khoản: `admin@vg.test` / `change-me`)

Điều hướng: Open /admin/login, focus email input

Tiền điều kiện dữ liệu: Browser fresh, no session cookie

Hành vi mong đợi: Submit valid creds → redirect /admin/dashboard

Vui lòng PASS / FAIL / SKIP với lý do.

---

## G-02: Sites list view

Truy cập: `/admin/sites` (Vai trò: `admin`, Tài khoản: `admin@vg.test` / `change-me`)

Điều hướng: Login as admin, click Sites tab

Tiền điều kiện dữ liệu: ≥1 site exists in fixture seed

Hành vi mong đợi: Sites table renders with at least one row

Vui lòng PASS / FAIL / SKIP với lý do.
"""

INVALID_NARRATIVE = """## G-01: Login flow

Truy cập: `/admin/login` (Vai trò: `admin`)

Điều hướng: Open /admin/login

# missing precondition + expected — BLOCK expected
"""


class TestUatNarrativeFields:
    def test_valid_narrative_passes(self, tmp_path):
        phase = _seed_phase_dir(tmp_path)
        (phase / "UAT-NARRATIVE.md").write_text(VALID_NARRATIVE, encoding="utf-8")
        r = _run_validator(VALIDATORS / "verify-uat-narrative-fields.py",
                           ["--phase", "15"], tmp_path)
        assert r.returncode == 0, f"valid narrative should PASS — stdout={r.stdout}"
        assert _verdict(r.stdout) in ("PASS", "WARN")

    def test_missing_fields_blocks(self, tmp_path):
        phase = _seed_phase_dir(tmp_path)
        (phase / "UAT-NARRATIVE.md").write_text(INVALID_NARRATIVE, encoding="utf-8")
        r = _run_validator(VALIDATORS / "verify-uat-narrative-fields.py",
                           ["--phase", "15"], tmp_path)
        assert r.returncode == 1, f"missing fields should BLOCK — got rc={r.returncode}"
        assert _verdict(r.stdout) == "BLOCK"


# ─── D-18 verify-uat-strings-no-hardcode.py ───────────────────────────────

class TestUatStringsNoHardcode:
    """Validator looks up narration-strings.yaml relative to VG_REPO_ROOT;
    these tests point that at the actual repo so the canonical strings
    file is found (commands/vg/_shared/narration-strings.yaml)."""

    def test_template_with_only_keys_passes(self, tmp_path):
        tpl = tmp_path / "narrative.tmpl.md"
        tpl.write_text(
            "## {{var.prompt_id}}: {{var.prompt_title}}\n\n"
            "{{uat_entry_label}}: `{{var.entry_url}}`\n",
            encoding="utf-8",
        )
        r = _run_validator(VALIDATORS / "verify-uat-strings-no-hardcode.py",
                           ["--template", str(tpl)], REPO_ROOT)
        assert r.returncode == 0, f"clean template should NOT BLOCK — stdout={r.stdout}"

    def test_template_referencing_unknown_uat_key_blocks(self, tmp_path):
        tpl = tmp_path / "broken.tmpl.md"
        tpl.write_text(
            "## {{var.prompt_id}}\n\n"
            "{{uat_totally_made_up_key}}: `{{var.entry_url}}`\n",
            encoding="utf-8",
        )
        r = _run_validator(VALIDATORS / "verify-uat-strings-no-hardcode.py",
                           ["--template", str(tpl)], REPO_ROOT)
        assert r.returncode == 1, f"unknown uat key should BLOCK — stdout={r.stdout}"
        assert _verdict(r.stdout) == "BLOCK"
        assert "uat_totally_made_up_key" in r.stdout


# ─── D-16 verify-filter-test-coverage.py ──────────────────────────────────
#
# The validator counts test() blocks whose name contains the control slug
# AND the kind keyword (filter/pagination). We seed a phase dir with a
# minimal TEST-GOALS.md declaring one filter + one pagination, then
# generate the rigor pack via filter-test-matrix.mjs and run the validator.

TEST_GOALS_INTERACTIVE = """## TEST-GOALS

```json
{
  "interactive_controls": {
    "filters": [
      { "name": "status", "values": ["draft", "active", "paused", "archived"] }
    ],
    "pagination": { "name": "page", "page_size": 20, "type": "offset" }
  }
}
```
"""


def _to_file_url(p: str) -> str:
    """Windows ESM imports need file:// scheme; POSIX accepts both. Normalise."""
    p_fwd = p.replace("\\", "/")
    if p_fwd.startswith("/"):
        return "file://" + p_fwd
    return "file:///" + p_fwd  # Windows drive-letter path


def _matrix_smoke_snippet(matrix_path: str, tpl_root: str, out_dir: str) -> str:
    return (
        "import { enumerateFilterFiles, enumeratePaginationFiles, renderTemplate } from "
        + json.dumps(_to_file_url(matrix_path)) + "\n"
        + "import fs from 'node:fs/promises'\n"
        + "const goal = { id: 'G-FIX', actor: 'admin', route: '/admin/fix' }\n"
        + "const filter = { name: 'status', values: ['draft','active','paused','archived'] }\n"
        + "const pagination = { name: 'page', page_size: 20 }\n"
        + "const tplRoot = " + json.dumps(tpl_root) + "\n"
        + "const outDir = " + json.dumps(out_dir) + "\n"
        + "let written = 0\n"
        + "for (const f of enumerateFilterFiles(goal, filter, { templateRoot: tplRoot })) {\n"
        + "  const body = await renderTemplate(f.template_path, f.vars)\n"
        + "  await fs.writeFile(outDir + '/' + f.slug + '.spec.ts', body, 'utf8')\n"
        + "  written++\n"
        + "}\n"
        + "for (const f of enumeratePaginationFiles(goal, pagination, { templateRoot: tplRoot })) {\n"
        + "  const body = await renderTemplate(f.template_path, f.vars)\n"
        + "  await fs.writeFile(outDir + '/' + f.slug + '.spec.ts', body, 'utf8')\n"
        + "  written++\n"
        + "}\n"
        + "console.log(JSON.stringify({ written }))\n"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node required for matrix renderer")
class TestFilterCodegen:
    def test_matrix_renders_expected_block_counts(self, tmp_path):
        out_dir = tmp_path / "generated"
        out_dir.mkdir()
        skills_path = REPO_ROOT / "skills" / "vg-codegen-interactive" / "filter-test-matrix.mjs"
        assert skills_path.exists(), f"matrix module not at {skills_path}"

        snippet = _matrix_smoke_snippet(
            matrix_path=str(skills_path).replace("\\", "/"),
            tpl_root=str(SHARED / "templates").replace("\\", "/"),
            out_dir=str(out_dir).replace("\\", "/"),
        )
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", snippet],
            cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
        )
        assert proc.returncode == 0, f"matrix smoke failed: stderr={proc.stderr}"
        report = json.loads(proc.stdout.strip())
        assert report["written"] == 10, (
            f"expected 4 filter + 6 pagination = 10 files; got {report['written']}"
        )

        import re as _re
        blk = _re.compile(r"\btest(?:\.skip|\.only|\.fixme)?\s*\(\s*[`'\"]([^`'\"]+)[`'\"]")
        f_blocks = p_blocks = 0
        for spec in out_dir.glob("*.spec.ts"):
            text = spec.read_text(encoding="utf-8")
            for m in blk.finditer(text):
                name = m.group(1).lower()
                if "status" in name and "filter" in name:
                    f_blocks += 1
                if "page" in name and "pagination" in name:
                    p_blocks += 1
        assert f_blocks == 13, f"expected 13 filter blocks per D-16; got {f_blocks}"
        assert p_blocks == 18, f"expected 18 pagination blocks per D-16; got {p_blocks}"

    def test_validator_passes_on_full_matrix(self, tmp_path):
        phase = _seed_phase_dir(tmp_path)
        (phase / "TEST-GOALS.md").write_text(TEST_GOALS_INTERACTIVE, encoding="utf-8")
        skills_path = REPO_ROOT / "skills" / "vg-codegen-interactive" / "filter-test-matrix.mjs"
        snippet = _matrix_smoke_snippet(
            matrix_path=str(skills_path).replace("\\", "/"),
            tpl_root=str(SHARED / "templates").replace("\\", "/"),
            out_dir=str(tmp_path).replace("\\", "/"),
        )
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", snippet],
            cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
        )
        assert proc.returncode == 0, f"matrix render failed: {proc.stderr}"

        r = _run_validator(VALIDATORS / "verify-filter-test-coverage.py",
                           ["--phase", "15", "--tests-glob", "*.spec.ts"], tmp_path)
        assert r.returncode == 0, f"full matrix should PASS — stdout={r.stdout} stderr={r.stderr}"
        assert _verdict(r.stdout) in ("PASS", "WARN")


# ─── D-02 verify-design-ref-required.py (profile gate, regression for B1) ─

PLAN_UI_NO_REF = """## Tasks

<task id="T-1">
  <file-path>apps/web/src/sites/SitesList.tsx</file-path>
  <description>Render sites list with table.</description>
</task>
"""

PLAN_UI_WITH_REF = """## Tasks

<task id="T-1">
  <file-path>apps/web/src/sites/SitesList.tsx</file-path>
  <design-ref slug="sites-list"/>
  <description>Render sites list with table.</description>
</task>
"""


class TestDesignRefRequiredProfile:
    """B1 regression: caller passes --profile production; without the flag
    arg accepted, argparse exited 2 → silent SKIP. These tests exercise
    the flag end-to-end so the bypass cannot recur."""

    def _run(self, tmp_path: Path, args: list[str]) -> subprocess.CompletedProcess:
        return _run_validator(VALIDATORS / "verify-design-ref-required.py",
                              args, tmp_path)

    def test_profile_flag_accepted(self, tmp_path):
        # Phase dir present but no PLAN — exits cleanly when flag is recognized
        _seed_phase_dir(tmp_path)
        r = self._run(tmp_path, ["--phase", "15", "--profile", "production"])
        assert "unrecognized arguments" not in (r.stderr or ""), (
            f"--profile must be a recognized arg — stderr={r.stderr}"
        )
        # rc 0 OR 1 (PASS / BLOCK) both indicate the script ran; rc 2 means argparse failure.
        assert r.returncode in (0, 1), f"argparse failure? rc={r.returncode} stderr={r.stderr}"

    def test_production_profile_blocks_missing_ref(self, tmp_path):
        phase = _seed_phase_dir(tmp_path)
        (phase / "PLAN.md").write_text(PLAN_UI_NO_REF, encoding="utf-8")
        r = self._run(tmp_path, ["--phase", "15", "--profile", "production"])
        assert r.returncode == 1, f"production + missing ref must BLOCK — stdout={r.stdout}"
        assert _verdict(r.stdout) == "BLOCK"

    def test_default_profile_warns_missing_ref(self, tmp_path):
        phase = _seed_phase_dir(tmp_path)
        (phase / "PLAN.md").write_text(PLAN_UI_NO_REF, encoding="utf-8")
        r = self._run(tmp_path, ["--phase", "15", "--profile", "default"])
        assert r.returncode == 0, f"default + missing ref must NOT BLOCK — stdout={r.stdout}"
        assert _verdict(r.stdout) == "WARN"

    def test_prototype_profile_advisory_only(self, tmp_path):
        phase = _seed_phase_dir(tmp_path)
        (phase / "PLAN.md").write_text(PLAN_UI_NO_REF, encoding="utf-8")
        r = self._run(tmp_path, ["--phase", "15", "--profile", "prototype"])
        assert r.returncode == 0, f"prototype must PASS — stdout={r.stdout}"
        assert _verdict(r.stdout) == "PASS"


# ─── D-12a verify-uimap-injection.py (regression for B2) ─────────────────

PROMPT_BOTH_MARKERS = """<!-- audit trail -->

## UI-MAP-SUBTREE-FOR-THIS-WAVE

- `PageLayout`
  - `SitesTable.w-full` (data: state.sites)

## DESIGN-REF

apps/web/src/sites/SitesList.tsx — uses sites-list.default.png reference.
"""

PROMPT_MISSING_UIMAP = """## DESIGN-REF

apps/web/src/sites/SitesList.tsx — uses sites-list.default.png reference.
"""

PROMPT_MISSING_DESIGN = """## UI-MAP-SUBTREE-FOR-THIS-WAVE

- `PageLayout`
  - `SitesTable.w-full` (data: state.sites)

apps/web/src/sites/SitesList.tsx — task body without DESIGN-REF section.
"""


class TestUimapInjection:
    """B2 regression: build.md previously injected `<ui_map_subtree>` XML tag
    and never persisted prompts to disk; validator soft-passed because no
    prompts to inspect. Tests below assert the H2 marker contract is
    enforced when prompts ARE persisted."""

    def _seed_prompts(self, tmp_path: Path, prompts: dict[str, str]) -> Path:
        phase = _seed_phase_dir(tmp_path)
        prompt_dir = phase / ".build" / "wave-1" / "executor-prompts"
        prompt_dir.mkdir(parents=True)
        for name, body in prompts.items():
            (prompt_dir / name).write_text(body, encoding="utf-8")
        return phase

    def test_prompt_with_both_markers_passes(self, tmp_path):
        self._seed_prompts(tmp_path, {"task-1.md": PROMPT_BOTH_MARKERS})
        r = _run_validator(VALIDATORS / "verify-uimap-injection.py",
                           ["--phase", "15"], tmp_path)
        assert r.returncode == 0, f"both markers should PASS — stdout={r.stdout}"
        assert _verdict(r.stdout) in ("PASS", "WARN")

    def test_prompt_missing_uimap_marker_blocks(self, tmp_path):
        self._seed_prompts(tmp_path, {"task-1.md": PROMPT_MISSING_UIMAP})
        r = _run_validator(VALIDATORS / "verify-uimap-injection.py",
                           ["--phase", "15"], tmp_path)
        assert r.returncode == 1, f"missing UI-MAP marker should BLOCK — stdout={r.stdout}"
        assert _verdict(r.stdout) == "BLOCK"
        assert "UI-MAP-SUBTREE-FOR-THIS-WAVE" in r.stdout

    def test_prompt_missing_design_ref_marker_blocks(self, tmp_path):
        self._seed_prompts(tmp_path, {"task-1.md": PROMPT_MISSING_DESIGN})
        r = _run_validator(VALIDATORS / "verify-uimap-injection.py",
                           ["--phase", "15"], tmp_path)
        assert r.returncode == 1, f"missing DESIGN-REF should BLOCK — stdout={r.stdout}"
        assert _verdict(r.stdout) == "BLOCK"
        assert "DESIGN-REF" in r.stdout


# ─── D-12a + D-14 extract-subtree-haiku.mjs ──────────────────────────────

@pytest.mark.skipif(shutil.which("node") is None, reason="node required for subtree extractor")
class TestExtractSubtree:
    def test_filters_to_owner_wave(self, tmp_path):
        # Use the valid UI-MAP fixture (has owner_wave_id wave-1 + wave-2).
        ui_map_src = FIXTURES / "uimap" / "valid.md"
        out_path = tmp_path / "subtree.json"
        proc = subprocess.run(
            [
                "node", str(SCRIPTS / "extract-subtree-haiku.mjs"),
                "--uimap", str(ui_map_src),
                "--owner-wave-id", "wave-2",
                "--format", "json",
                "--output", str(out_path),
            ],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        assert proc.returncode == 0, f"subtree extractor failed: {proc.stderr}"
        assert out_path.exists()
        subtree = json.loads(out_path.read_text(encoding="utf-8"))
        # wave-2 owns MainContent (id=main-1) — root should be PageLayout with
        # only the MainContent child kept (Topbar dropped).
        assert subtree.get("tag") == "PageLayout"
        kept_ids = [c.get("id") for c in subtree.get("children", [])]
        assert kept_ids == ["main-1"], f"expected only main-1 kept; got {kept_ids}"

    def test_unknown_wave_returns_empty_subtree(self, tmp_path):
        ui_map_src = FIXTURES / "uimap" / "valid.md"
        out_path = tmp_path / "empty.json"
        proc = subprocess.run(
            [
                "node", str(SCRIPTS / "extract-subtree-haiku.mjs"),
                "--uimap", str(ui_map_src),
                "--owner-wave-id", "wave-does-not-exist",
                "--format", "json",
                "--output", str(out_path),
            ],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        # Exit 0 even when empty (per script convention) — empty marker is the contract
        assert proc.returncode == 0, f"empty subtree should still exit 0: {proc.stderr}"
        subtree = json.loads(out_path.read_text(encoding="utf-8"))
        assert subtree.get("tag") == "(empty)", f"expected empty marker; got {subtree}"
