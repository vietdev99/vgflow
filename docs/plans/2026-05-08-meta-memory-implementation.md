# Meta-Memory Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend VG bootstrap with `procedural` rule type + 5 reflector triggers (deploy/test/accept/roam/amend) + 4 inject sites + Dreams-style 4-phase consolidation, with causal attribution gate to prevent cargo-cult learning.

**Architecture:** Reuse existing bootstrap infra (`bootstrap-loader.py`, `bootstrap-shadow-evaluator.py`, `bootstrap-inject.sh`). Add new schema fields (`type`, `authority`, `conditions{all_of,any_of}`, `attribution_required`, `sequence`, `success_signals`). Reflector spawns post-deploy/test/accept/roam/amend → drafts candidates with sequence checksums → outcome prober verifies per-step execution → shadow evaluator gates promotion (≥5 samples + correctness 0.8). Consolidation merges in-place (Anthropic Auto Dream pattern), 4-phase: Orient → Gather → Consolidate → Prune.

**Tech Stack:** Python 3.x (`bootstrap-*.py` scripts), Bash (hook + inject sites), YAML frontmatter (rule files), SQLite (events.db), pytest (validators + integration).

**Source design:** `docs/plans/2026-05-08-meta-memory-design.md` Section 13 (v1.1).

**Critical risk mitigation (Codex #9):** Causal misattribution. Stage 3 (sequence checksum + per-step attribution prober) is HARD-GATED before Stage 4 (inject sites). Without Stage 3, procedural rules cannot be promoted.

**Rollout flag:** `vg.config.md → meta_memory_mode={disabled, reflect-only, inject-as-advice, default}`. Default `disabled`. Each stage flips one mode forward.

---

## Stage 0: Pre-flight (verify dependencies)

### Task 0.1: Verify existing infra is intact

**Files (read-only):**
- Read: `.claude/scripts/bootstrap-loader.py`
- Read: `.claude/scripts/bootstrap-shadow-evaluator.py`
- Read: `commands/vg/_shared/lib/bootstrap-inject.sh`
- Read: `commands/vg/_shared/reflection-trigger.md`
- Read: `.codex/skills/vg-reflector/SKILL.md`

**Step 1: Confirm scripts exist and are executable**

Run: `ls -la .claude/scripts/bootstrap-{loader,shadow-evaluator,conflict-detector,hygiene}.py`
Expected: all 4 files listed, executable bit set.

**Step 2: Confirm reflector skill schema enum**

Run: `grep -n "target_step:" .codex/skills/vg-reflector/SKILL.md | head -5`
Expected: line ~296 shows `{scope|blueprint|build|review|test|accept|global}` — confirms enum needs extension.

**Step 3: Confirm shadow evaluator threshold**

Run: `grep -nE "(min_samples|shadow_min_phases|correctness)" .claude/scripts/bootstrap-shadow-evaluator.py | head -10`
Expected: shows existing threshold logic to reuse.

**Step 4: Commit baseline tag**

```bash
git tag pre-meta-memory-v1.1
git push origin pre-meta-memory-v1.1
```

---

## Stage 1: Schema v1.1 + validator (Sections 13.3, 13.4)

### Task 1.1: Add `type` + `authority` + `conditions` schema fields

**Files:**
- Modify: `.codex/skills/vg-reflector/SKILL.md` (lines ~286-342)
- Modify: `codex-skills/vg-reflector/SKILL.md` (mirror)
- Modify: `codex-skills/vg-lesson/SKILL.md:207` (target_step enum)
- Modify: `.codex/skills/vg-lesson/SKILL.md:207`
- Test: `tests/test_rule_schema_v1_1.py` (NEW)

**Step 1: Write failing test for new schema fields**

```python
# tests/test_rule_schema_v1_1.py
import yaml
from pathlib import Path

def test_schema_doc_has_type_field():
    skill = Path(".codex/skills/vg-reflector/SKILL.md").read_text(encoding="utf-8")
    assert "type: rule | config_override | patch | procedural | declarative" in skill or \
           "type:" in skill and "procedural" in skill, \
        "vg-reflector SKILL.md must document type field with procedural value"

def test_schema_doc_has_authority_field():
    skill = Path(".codex/skills/vg-reflector/SKILL.md").read_text(encoding="utf-8")
    assert "authority: advisory" in skill, \
        "vg-reflector SKILL.md must document authority: advisory field"

def test_schema_doc_has_conditions_dsl():
    skill = Path(".codex/skills/vg-reflector/SKILL.md").read_text(encoding="utf-8")
    assert "all_of:" in skill and "any_of:" in skill, \
        "Schema must document conditions DSL all_of/any_of"

def test_target_step_enum_includes_deploy_roam_amend():
    skill = Path(".codex/skills/vg-reflector/SKILL.md").read_text(encoding="utf-8")
    for step in ("deploy", "roam", "amend"):
        assert step in skill, f"target_step enum must include '{step}'"
```

**Step 2: Run tests — verify failure**

Run: `python -m pytest tests/test_rule_schema_v1_1.py -v`
Expected: 4 FAIL (fields not yet documented).

**Step 3: Update SKILL.md schema docs**

In `.codex/skills/vg-reflector/SKILL.md` around line 286-300, replace old schema block with:

```yaml
- id: L-{PROPOSED_ID}
  draft_source: reflector.{step}.phase-{phase}
  type: rule | config_override | patch | procedural | declarative
  authority: advisory       # advisory only in v1; reference allowed; executable BLOCKED
  title: "{short, <80 chars}"

  conditions:
    all_of:
      - "{predicate}"
    any_of:
      - "{predicate}"

  target_step: scope|blueprint|build|review|test|accept|deploy|roam|amend|global
  action: must_run|add_check|warn|suggest|override

  # Procedural-only fields:
  sequence:
    - id: step1
      cmd: "{command string}"
      expected_signals: ["{signal1}", "{signal2}"]
  success_signals:
    - "{event_pattern}"
  attribution_required: true
  shadow_evaluator: true
  shadow_min_samples: 5
  shadow_min_correctness: 0.8

  fingerprint:
    repo_id: "{repo}"
    deploy_target: "{env}"
    health_cmd: "{cmd}"
    package_manager: "{npm|yarn|pnpm}"
    dockerfile_hash: "{sha256}"
```

Mirror change to `codex-skills/vg-reflector/SKILL.md`.

In both `vg-lesson/SKILL.md:207`, replace target_step enum with:
`{build|review|scope|blueprint|test|accept|deploy|roam|amend|global}`

**Step 4: Run tests — verify pass**

Run: `python -m pytest tests/test_rule_schema_v1_1.py -v`
Expected: 4 PASS.

**Step 5: Commit**

```bash
git add .codex/skills/vg-reflector/SKILL.md codex-skills/vg-reflector/SKILL.md \
        .codex/skills/vg-lesson/SKILL.md codex-skills/vg-lesson/SKILL.md \
        tests/test_rule_schema_v1_1.py
git commit -m "feat(meta-memory): schema v1.1 — add type/authority/conditions/sequence fields

Extends rule schema in vg-reflector + vg-lesson SKILL.md:
- type: declarative | procedural (default declarative for backwards compat)
- authority: advisory (executable blocked in v1)
- conditions: all_of/any_of DSL replacing applies_when_all_match
- target_step: extended with deploy|roam|amend
- procedural fields: sequence[], success_signals[], attribution_required
- shadow_evaluator gating: min_samples=5, correctness=0.8
- fingerprint: repo_id + deploy_target + health_cmd + package_manager + dockerfile_hash

Stage 1 of meta-memory implementation. Existing rules without 'type'
default to declarative (no migration). See Section 13.3 in design doc.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 1.2: Schema validator script

**Files:**
- Create: `.claude/scripts/validators/verify-rule-schema-v1-1.py`
- Test: `tests/test_verify_rule_schema_v1_1.py`

**Step 1: Write failing tests**

```python
# tests/test_verify_rule_schema_v1_1.py
import subprocess
import tempfile
from pathlib import Path
import textwrap

VALIDATOR = ".claude/scripts/validators/verify-rule-schema-v1-1.py"

def run_validator(rule_yaml: str) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(f"---\n{rule_yaml}\n---\n# body\n")
        path = f.name
    return subprocess.run(["python", VALIDATOR, path], capture_output=True, text=True)

def test_declarative_default_passes():
    result = run_validator(textwrap.dedent("""
        slug: test-rule
        title: "test"
        target_step: build
        priority: low
        tier: C
    """).strip())
    assert result.returncode == 0, result.stderr

def test_procedural_without_sequence_fails():
    result = run_validator(textwrap.dedent("""
        slug: bad-procedural
        title: "missing sequence"
        type: procedural
        target_step: deploy
    """).strip())
    assert result.returncode != 0
    assert "sequence" in result.stderr.lower()

def test_procedural_without_success_signals_fails():
    result = run_validator(textwrap.dedent("""
        slug: bad-procedural-2
        title: "missing signals"
        type: procedural
        target_step: deploy
        sequence:
          - id: s1
            cmd: "echo hi"
    """).strip())
    assert result.returncode != 0
    assert "success_signals" in result.stderr.lower()

def test_target_step_invalid_value_fails():
    result = run_validator(textwrap.dedent("""
        slug: bad-step
        title: "bad target_step"
        target_step: foobar
    """).strip())
    assert result.returncode != 0
    assert "target_step" in result.stderr.lower()

def test_target_step_deploy_passes():
    result = run_validator(textwrap.dedent("""
        slug: deploy-ok
        title: "ok"
        type: procedural
        authority: advisory
        target_step: deploy
        sequence:
          - id: s1
            cmd: "flyctl deploy"
            expected_signals: ["exit=0"]
        success_signals: ["phase.deploy_completed.outcome == PASS"]
        attribution_required: true
    """).strip())
    assert result.returncode == 0, result.stderr

def test_authority_executable_blocked():
    result = run_validator(textwrap.dedent("""
        slug: blocked
        title: "executable blocked"
        type: procedural
        authority: executable
        target_step: deploy
        sequence:
          - id: s1
            cmd: "echo"
            expected_signals: []
        success_signals: []
    """).strip())
    assert result.returncode != 0
    assert "authority" in result.stderr.lower()

def test_relative_date_in_body_fails():
    result = run_validator(textwrap.dedent("""
        slug: relative-date
        title: "test"
        target_step: build
    """).strip() + "\n---\n# body\nFixed yesterday's deploy bug.\n")
    assert result.returncode != 0
    assert "relative" in result.stderr.lower() or "date" in result.stderr.lower()
```

Wait — `run_validator` writes the body inside the helper. Adjust the last test to call with body separately. Cleaner version:

```python
def run_validator_with_body(rule_yaml: str, body: str = "# body\n") -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(f"---\n{rule_yaml}\n---\n{body}")
        path = f.name
    return subprocess.run(["python", VALIDATOR, path], capture_output=True, text=True)

def test_relative_date_in_body_fails():
    result = run_validator_with_body(
        textwrap.dedent("""
            slug: relative-date
            title: "test"
            target_step: build
        """).strip(),
        body="Fixed yesterday's deploy bug.\n",
    )
    assert result.returncode != 0
```

**Step 2: Run tests — verify failure**

Run: `python -m pytest tests/test_verify_rule_schema_v1_1.py -v`
Expected: all FAIL with "validator not found".

**Step 3: Implement validator**

```python
#!/usr/bin/env python3
"""Validate rule frontmatter against meta-memory v1.1 schema.

Exit 0 = valid. Exit 1 = invalid. stderr explains why.
"""
import re
import sys
from pathlib import Path

import yaml

ALLOWED_TARGET_STEPS = {
    "scope", "blueprint", "build", "review", "test", "accept",
    "deploy", "roam", "amend", "global",
}
ALLOWED_TYPES = {"declarative", "procedural", "rule", "config_override", "patch", "retract"}
ALLOWED_AUTHORITY = {"advisory", "reference"}  # NOT executable in v1
RELATIVE_DATE_RE = re.compile(
    r"\b(yesterday|today|tomorrow|last\s+(week|month|year)|next\s+(week|month|year))\b",
    re.IGNORECASE,
)


def parse_rule(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("rule file must start with YAML frontmatter `---`")
    rest = text[4:]
    end = rest.find("\n---\n")
    if end < 0:
        raise ValueError("frontmatter not closed with `---`")
    front = yaml.safe_load(rest[:end]) or {}
    body = rest[end + 5:]
    return front, body


def validate(front: dict, body: str) -> list[str]:
    errors: list[str] = []

    target_step = front.get("target_step")
    if target_step not in ALLOWED_TARGET_STEPS:
        errors.append(f"target_step={target_step!r} invalid; must be one of {sorted(ALLOWED_TARGET_STEPS)}")

    rtype = front.get("type", "declarative")
    if rtype not in ALLOWED_TYPES:
        errors.append(f"type={rtype!r} invalid; must be one of {sorted(ALLOWED_TYPES)}")

    authority = front.get("authority", "advisory")
    if authority not in ALLOWED_AUTHORITY:
        errors.append(f"authority={authority!r} invalid; must be one of {sorted(ALLOWED_AUTHORITY)} (executable BLOCKED in v1)")

    if rtype == "procedural":
        if not front.get("sequence"):
            errors.append("procedural rule requires non-empty sequence[]")
        if not front.get("success_signals"):
            errors.append("procedural rule requires non-empty success_signals[]")
        if front.get("attribution_required") is not True:
            errors.append("procedural rule requires attribution_required: true")
    else:
        if front.get("sequence"):
            errors.append(f"non-procedural rule (type={rtype!r}) must NOT define sequence[]")

    if RELATIVE_DATE_RE.search(body):
        errors.append("rule body contains relative date (yesterday/today/last week/etc); use absolute YYYY-MM-DD")

    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: verify-rule-schema-v1-1.py <rule.md>", file=sys.stderr)
        return 2
    try:
        front, body = parse_rule(Path(argv[1]))
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 1
    errors = validate(front, body)
    if errors:
        for err in errors:
            print(f"INVALID: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

**Step 4: Run tests — verify pass**

Run: `python -m pytest tests/test_verify_rule_schema_v1_1.py -v`
Expected: 7 PASS.

**Step 5: Commit**

```bash
git add .claude/scripts/validators/verify-rule-schema-v1-1.py tests/test_verify_rule_schema_v1_1.py
git commit -m "feat(meta-memory): rule schema v1.1 validator

Validates target_step enum (incl deploy/roam/amend), procedural-required
fields (sequence + success_signals + attribution_required), authority
gate (executable BLOCKED), and relative-date detection in body.

Exits 0 valid / 1 invalid with explanatory stderr.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Stage 2: 5 reflector triggers (Section 13.5)

### Task 2.1: Add post-deploy reflector trigger

**Files:**
- Modify: `commands/vg/_shared/reflection-trigger.md` (append new trigger block)
- Modify: `commands/vg/deploy.md` (insert spawn block after `phase.deploy_completed` emit ~line 466)
- Test: `tests/test_post_deploy_reflector_wiring.py`

**Step 1: Write failing test**

```python
# tests/test_post_deploy_reflector_wiring.py
from pathlib import Path

def test_deploy_md_spawns_reflector_after_completion():
    deploy = Path("commands/vg/deploy.md").read_text(encoding="utf-8")
    assert "vg-reflector" in deploy and "phase.deploy_completed" in deploy, \
        "deploy.md must spawn vg-reflector after phase.deploy_completed event"
    assert "meta_memory_mode" in deploy, \
        "deploy.md spawn must be gated by meta_memory_mode flag"

def test_reflection_trigger_doc_lists_deploy():
    doc = Path("commands/vg/_shared/reflection-trigger.md").read_text(encoding="utf-8")
    assert "post-deploy" in doc.lower() or "phase.deploy_completed" in doc, \
        "reflection-trigger.md must document post-deploy hook"
```

**Step 2: Run — verify FAIL**

Run: `python -m pytest tests/test_post_deploy_reflector_wiring.py -v`
Expected: 2 FAIL.

**Step 3: Wire up in deploy.md**

After existing `phase.deploy_completed` emit block (around line 466), insert:

```bash
# Meta-memory v1.1: post-deploy reflector trigger (Section 13.5)
META_MEMORY_MODE=$(grep -E "^meta_memory_mode:" vg.config.md 2>/dev/null | awk '{print $2}' || echo "disabled")
if [ "$META_MEMORY_MODE" != "disabled" ] && [ "$EVENT_TYPE" = "phase.deploy_completed" ]; then
  # Spawn vg-reflector subagent — caller-side narration required
  bash scripts/vg-narrate-spawn.sh vg-reflector spawning "post-deploy candidate draft"
  # Spawn happens in parent agent context — see SKILL.md REFLECT_STEP=deploy
  ${PYTHON_BIN:-python3} .claude/scripts/vg-orchestrator emit-event \
    "reflection.trigger_requested" --actor "deploy" --outcome "INFO" \
    --metadata '{"step":"deploy","phase":"'$PHASE'","trigger":"post-deploy"}'
fi
```

In `commands/vg/_shared/reflection-trigger.md`, append a new section:

```markdown
## post-deploy (NEW v1.1)

**Trigger event:** `phase.deploy_completed` (any outcome).

**Inputs to reflector:**
- `events.db` query: `deploy.{started,completed,failed}` for current phase
- `${PHASE_DIR}/DEPLOY-STATE.json` `deployed.{env}` block
- `${PHASE_DIR}/.deploy-log.{env}.txt` per env stdout/stderr
- `vg.config.md` env list, deploy commands, package manager

**Candidate target:** `target_step=deploy`, `type=procedural`.

**Fingerprint:** `hash(repo_id + deploy_target + health_cmd + env + commands + dockerfile_hash + package_manager)`.

**Gating:** `vg.config.md → meta_memory_mode != "disabled"`.
```

**Step 4: Run — verify PASS**

Run: `python -m pytest tests/test_post_deploy_reflector_wiring.py -v`
Expected: 2 PASS.

**Step 5: Commit**

```bash
git add commands/vg/deploy.md commands/vg/_shared/reflection-trigger.md \
        tests/test_post_deploy_reflector_wiring.py
git commit -m "feat(meta-memory): add post-deploy reflector trigger

Stage 2 task 1/5. Wires phase.deploy_completed → vg-reflector spawn,
gated by meta_memory_mode flag. Reflector inputs: events.db, DEPLOY-STATE.json,
per-env deploy log, vg.config.md. Documented in reflection-trigger.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.2: Add post-test reflector trigger

**Files:**
- Modify: `commands/vg/test.md` (insert after test completion emit)
- Modify: `commands/vg/_shared/reflection-trigger.md` (append section)
- Test: `tests/test_post_test_reflector_wiring.py`

Same TDD shape as Task 2.1 (write test → fail → wire → pass → commit).

**Trigger event:** `phase.test_completed`. **Inputs:** events.db `test.* + codegen.*`, TEST-GOALS verdicts, fix-loop iteration count. **Candidate target:** `target_step=test`, `type=declarative|procedural` (auto-detect).

---

### Task 2.3: Add post-accept reflector trigger

**Files:**
- Modify: `commands/vg/accept.md`
- Modify: `commands/vg/_shared/reflection-trigger.md`
- Test: `tests/test_post_accept_reflector_wiring.py`

**Trigger event:** `phase.accept_uat_completed`. **Inputs:** UAT-CHECKLIST.md verdicts, events.db `gate.fired`, structured digest of user msgs (no raw transcript). **Candidate target:** `target_step=accept`, `type=declarative`.

---

### Task 2.4: Add post-roam reflector trigger (Codex #2)

**Files:**
- Modify: `commands/vg/roam.md`
- Modify: `commands/vg/_shared/reflection-trigger.md`
- Test: `tests/test_post_roam_reflector_wiring.py`

**Trigger event:** `phase.roam_completed`. **Inputs:** roam findings JSON, state-mismatch report. **Candidate target:** `target_step=roam`, `type=declarative` (caught patterns).

**Why critical:** Codex #2 noted roam catches bugs review/test miss → high-signal reflector input.

---

### Task 2.5: Add post-amend reflector trigger (Codex #2)

**Files:**
- Modify: `commands/vg/amend.md`
- Modify: `commands/vg/_shared/reflection-trigger.md`
- Test: `tests/test_post_amend_reflector_wiring.py`

**Trigger event:** `phase.amend_committed`. **Inputs:** AMENDMENT-LOG.md, diff between old/new CONTEXT.md decisions. **Candidate target:** `type=retract` — invalidate rules whose preconditions reference removed decisions.

**Why critical:** Codex #2 — without this, rules learned from prior scope persist after scope change → contradiction.

---

## Stage 3: Causal attribution (CRITICAL — Codex #9)

> **Hard gate:** Stage 4 inject sites MUST NOT proceed until Stage 3 ships. Without sequence checksum + per-step attribution, procedural promotion is cargo-cult.

### Task 3.1: Sequence checksum at fire time

**Files:**
- Modify: `commands/vg/_shared/lib/bootstrap-inject.sh:88-140` (`vg_bootstrap_emit_fired` function)
- Test: `tests/test_bootstrap_emit_fired_checksum.py`

**Step 1: Write failing test**

```python
# tests/test_bootstrap_emit_fired_checksum.py
import hashlib
import json
import subprocess
from pathlib import Path

def test_emit_fired_includes_sequence_checksum(tmp_path):
    """When a procedural rule fires, the bootstrap.rule_fired event payload
    MUST include sequence_checksum = sha256 of joined sequence cmds."""
    rule_file = tmp_path / "rule.md"
    rule_file.write_text(
        "---\n"
        "slug: test-rule\n"
        "type: procedural\n"
        "authority: advisory\n"
        "target_step: deploy\n"
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: 'npm run build'\n"
        "    expected_signals: ['exit=0']\n"
        "  - id: s2\n"
        "    cmd: 'flyctl deploy'\n"
        "    expected_signals: ['exit=0']\n"
        "success_signals: ['phase.deploy_completed.outcome == PASS']\n"
        "attribution_required: true\n"
        "---\n# body\n",
        encoding="utf-8",
    )
    expected_checksum = hashlib.sha256(b"npm run build\nflyctl deploy").hexdigest()
    # Source the helper, call function, capture emitted event
    cmd = [
        "bash", "-c",
        f"source commands/vg/_shared/lib/bootstrap-inject.sh && "
        f"vg_bootstrap_emit_fired '{rule_file}' --json"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("sequence_checksum") == expected_checksum
```

**Step 2: Run — FAIL**

Run: `python -m pytest tests/test_bootstrap_emit_fired_checksum.py -v`

**Step 3: Patch `bootstrap-inject.sh`**

In `vg_bootstrap_emit_fired()`, before existing emit block, compute and attach checksum:

```bash
# Section 13.4 — sequence checksum for causal attribution
if [ "$(yq '.type' "$RULE_FILE")" = "procedural" ]; then
  SEQ=$(yq '.sequence[].cmd' "$RULE_FILE" | tr -d '"')
  SEQ_CHECKSUM=$(printf '%s' "$SEQ" | sha256sum | awk '{print $1}')
  EXTRA_METADATA="\"sequence_checksum\":\"${SEQ_CHECKSUM}\","
else
  EXTRA_METADATA=""
fi
# (existing emit-event call augmented with EXTRA_METADATA into --metadata JSON)
```

**Step 4: Run — PASS**

**Step 5: Commit** (`feat(meta-memory): sequence checksum on rule fire — Codex #9 attribution`)

---

### Task 3.2: Per-step execution prober

**Files:**
- Create: `.claude/scripts/bootstrap-attribute-outcome.py`
- Test: `tests/test_bootstrap_attribute_outcome.py`

**Step 1: Failing test**

```python
# tests/test_bootstrap_attribute_outcome.py
import json
import subprocess
import tempfile
from pathlib import Path

PROBER = ".claude/scripts/bootstrap-attribute-outcome.py"

def test_full_match_returns_executed_steps(tmp_path):
    rule = tmp_path / "rule.md"
    rule.write_text(
        "---\n"
        "slug: test\n"
        "type: procedural\n"
        "authority: advisory\n"
        "target_step: deploy\n"
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: 'npm run build'\n"
        "    expected_signals: ['exit=0']\n"
        "  - id: s2\n"
        "    cmd: 'flyctl deploy --remote-only'\n"
        "    expected_signals: ['exit=0']\n"
        "success_signals: []\n"
        "attribution_required: true\n"
        "---\n",
        encoding="utf-8",
    )
    deploy_log = tmp_path / "deploy.log"
    deploy_log.write_text(
        "$ npm run build\n"
        "built in 3.2s\n"
        "exit 0\n"
        "$ flyctl deploy --remote-only\n"
        "==> Building image...\n"
        "exit 0\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["python", PROBER, "--rule", str(rule), "--log", str(deploy_log), "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["executed_step_ids"] == ["s1", "s2"]
    assert payload["total_steps"] == 2
    assert payload["matched_signals_count"] == 2

def test_partial_match_returns_subset(tmp_path):
    rule = tmp_path / "rule.md"
    rule.write_text(
        "---\nslug: t\ntype: procedural\nauthority: advisory\ntarget_step: deploy\n"
        "sequence:\n  - id: s1\n    cmd: 'npm run build'\n    expected_signals: ['exit=0']\n"
        "  - id: s2\n    cmd: 'flyctl deploy'\n    expected_signals: ['exit=0']\n"
        "success_signals: []\nattribution_required: true\n---\n",
        encoding="utf-8",
    )
    log = tmp_path / "log.txt"
    log.write_text("$ npm run build\nexit 0\n", encoding="utf-8")
    result = subprocess.run(
        ["python", PROBER, "--rule", str(rule), "--log", str(log), "--json"],
        capture_output=True, text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["executed_step_ids"] == ["s1"]
    assert payload["total_steps"] == 2

def test_no_execution_returns_empty(tmp_path):
    rule = tmp_path / "rule.md"
    rule.write_text(
        "---\nslug: t\ntype: procedural\nauthority: advisory\ntarget_step: deploy\n"
        "sequence:\n  - id: s1\n    cmd: 'npm run build'\n    expected_signals: ['exit=0']\n"
        "success_signals: []\nattribution_required: true\n---\n",
        encoding="utf-8",
    )
    log = tmp_path / "empty.txt"
    log.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["python", PROBER, "--rule", str(rule), "--log", str(log), "--json"],
        capture_output=True, text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["executed_step_ids"] == []
```

**Step 2: Run — FAIL.**

**Step 3: Implement prober**

```python
#!/usr/bin/env python3
"""Per-step execution prober for procedural rules (Section 13.4).

Reads rule.sequence[] and a deploy/test log, returns:
  - executed_step_ids: which steps actually ran (cmd substring match)
  - matched_signals_count: how many expected_signals matched
  - total_steps: rule.sequence length

Output as JSON. Used by consolidator to gate causal attribution.
"""
import argparse
import json
import re
import sys
from pathlib import Path
import yaml


def parse_rule(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("frontmatter not closed")
    return yaml.safe_load(text[4:end]) or {}


def probe(rule: dict, log_text: str) -> dict:
    sequence = rule.get("sequence") or []
    executed = []
    matched_signals = 0
    cursor = 0
    for step in sequence:
        sid = step.get("id")
        cmd = step.get("cmd", "")
        # Match cmd substring after current cursor (preserves ordering)
        idx = log_text.find(cmd, cursor)
        if idx >= 0:
            executed.append(sid)
            cursor = idx + len(cmd)
            for sig in step.get("expected_signals", []) or []:
                if sig in log_text[idx:idx + 4096]:
                    matched_signals += 1
    return {
        "executed_step_ids": executed,
        "total_steps": len(sequence),
        "matched_signals_count": matched_signals,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    rule = parse_rule(Path(args.rule))
    log_text = Path(args.log).read_text(encoding="utf-8", errors="replace")
    result = probe(rule, log_text)
    if args.json:
        print(json.dumps(result))
    else:
        print(f"executed: {len(result['executed_step_ids'])}/{result['total_steps']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

**Step 4: Run — PASS.**

**Step 5: Commit** (`feat(meta-memory): per-step attribution prober — Codex #9 mitigation`)

---

### Task 3.3: Outcome event schema extension

**Files:**
- Modify: `.claude/schemas/event.json` (add `attribution` field to `bootstrap.outcome_recorded`)
- Modify: `.claude/scripts/vg-orchestrator/__main__.py:3418` (the outcome emit block)
- Test: `tests/test_outcome_event_attribution.py`

**Step 1: Failing test**

```python
def test_outcome_event_requires_attribution_for_procedural(tmp_path):
    # emit-event with bootstrap.outcome_recorded for type=procedural rule
    # without attribution payload → should reject with non-zero exit
    result = subprocess.run([
        "python", ".claude/scripts/vg-orchestrator", "emit-event",
        "bootstrap.outcome_recorded",
        "--actor", "test",
        "--outcome", "PASS",
        "--metadata", json.dumps({"slug": "test-procedural", "rule_type": "procedural"}),
    ], capture_output=True, text=True)
    assert result.returncode != 0
    assert "attribution" in result.stderr.lower()
```

**Step 2-4: Wire — orchestrator emit-event for `bootstrap.outcome_recorded` checks `metadata.rule_type == "procedural"` and rejects without `metadata.attribution.executed_step_ids`.**

**Step 5: Commit** (`feat(meta-memory): outcome event requires attribution for procedural`)

---

## Stage 4: Inject sites (Section 13.5) — gated by Stage 3 completion

### Task 4.1: `/vg:build` STEP 0.5 preflight inject

**Files:**
- Modify: `commands/vg/_shared/build/preflight.md`
- Test: `tests/test_build_preflight_meta_memory_inject.py`

**Step 1: Failing test**

```python
def test_preflight_loads_meta_memory_when_enabled(tmp_path, monkeypatch):
    # Seed config flag, run preflight script, assert .build-context.md mentions rules
    ...
```

**Step 2-4: Insert before existing context-load:**

```bash
# Meta-memory v1.1 (Section 5.1): build preflight inject
META_MEMORY_MODE=$(grep -E "^meta_memory_mode:" vg.config.md | awk '{print $2}' || echo "disabled")
if [ "$META_MEMORY_MODE" = "inject-as-advice" ] || [ "$META_MEMORY_MODE" = "default" ]; then
  RULES_BLOCK=$(${PYTHON_BIN:-python3} .claude/scripts/bootstrap-loader.py \
    --target-step build \
    --target-step deploy \
    --include-procedural \
    --filter-preconditions "$(cat ${PHASE_DIR}/.phase-context.json 2>/dev/null || echo '{}')" \
    --max-bytes 8192 || echo "")
  if [ -n "$RULES_BLOCK" ]; then
    {
      echo "## Meta-Memory Rules (procedural+declarative, $(date -Iseconds))"
      echo
      echo "$RULES_BLOCK"
    } >> ${PHASE_DIR}/.build-context.md
  fi
fi
```

**Step 5: Commit.**

---

### Task 4.2: `/vg:deploy` STEP 0 pre-spawn inject

**Files:**
- Modify: `commands/vg/deploy.md` (before line 401 spawn block)
- Test: `tests/test_deploy_pre_spawn_inject.py`

**Step 1-4: Insert load block, pass via `BOOTSTRAP_RULES_BLOCK` env var to vg-deploy-executor capsule. Filter by `target_step=deploy`, `--filter-preconditions` from current phase context (env, dockerfile flag).**

**Step 5: Commit.**

---

### Task 4.3: `/vg:accept` STEP 1 preflight inject

**Files:**
- Modify: `commands/vg/_shared/accept/preflight.md`
- Test: `tests/test_accept_preflight_inject.py`

Mirror of Task 4.1 with `target_step=accept`.

---

### Task 4.4: Extend `bootstrap-inject.sh` filter for procedural rules

**Files:**
- Modify: `commands/vg/_shared/lib/bootstrap-inject.sh:40-64`
- Test: `tests/test_bootstrap_inject_procedural_filter.py`

**Step 1: Failing test** — `vg_bootstrap_render_block` MUST render procedural rules differently from declarative (different markdown header).

**Step 2-4: Render two sections:**

```markdown
### Declarative Rules (MUST do/MUST NOT do)
{declarative bullet list}

### Procedural Recipes (worked previously with matching context)
{procedural sequence + success_signals, marked as ADVISORY}
```

**Step 5: Commit.**

---

## Stage 5: Dreams 4-phase consolidation (Section 13.1)

### Task 5.1: Lock file + 24h+5sessions trigger gate

**Files:**
- Create: `.claude/scripts/bootstrap-consolidate.py` (skeleton + orient phase)
- Test: `tests/test_consolidate_trigger_gate.py`

**Step 1: Failing test**

```python
def test_consolidate_skips_when_under_24h(tmp_path):
    # Set last-run timestamp to 1h ago, run consolidate, assert skip
    ...

def test_consolidate_skips_when_under_5_sessions(tmp_path):
    # Set last-run 26h ago but session count = 3, assert skip
    ...

def test_consolidate_runs_when_both_gates_passed(tmp_path):
    ...

def test_lock_file_prevents_concurrent(tmp_path):
    # Create stale lock, run, assert refusal with message
    ...
```

**Step 2-4: Implement gate logic in `bootstrap-consolidate.py`:**

```python
GATE_HOURS = 24
GATE_SESSIONS = 5
LOCK = Path(".vg/bootstrap/.consolidation.lock")

def check_gate(state_file: Path) -> tuple[bool, str]:
    if LOCK.exists():
        return False, "consolidation already running (lock present)"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    last = state.get("last_run_ts", 0)
    sessions = state.get("sessions_since_last", 0)
    now = time.time()
    if now - last < GATE_HOURS * 3600:
        return False, f"<{GATE_HOURS}h since last run"
    if sessions < GATE_SESSIONS:
        return False, f"<{GATE_SESSIONS} sessions since last run"
    return True, "OK"
```

**Step 5: Commit.**

---

### Task 5.2: Phase 1 — Orient

**Files:**
- Modify: `bootstrap-consolidate.py` add `phase_orient()`
- Test: `tests/test_consolidate_orient.py`

**Logic:** `view` `.vg/bootstrap/` directory listing, MEMORY.md size, count of CANDIDATES/ACCEPTED/REJECTED, last consolidation date. Output JSON snapshot.

---

### Task 5.3: Phase 2 — Gather Signal

**Files:**
- Modify: `bootstrap-consolidate.py` add `phase_gather()`
- Test: `tests/test_consolidate_gather.py`

**Logic:**
1. Query events.db: `bootstrap.rule_fired + bootstrap.outcome_recorded` last 100 sessions OR 30 days, whichever smaller.
2. **Narrow grep** on session JSONL transcripts (Anthropic actual): user-correction patterns, explicit-save patterns, recurring-theme patterns. NO full read.
3. Group by rule slug + fingerprint.
4. For procedural rules: filter to outcomes WHERE `attribution.executed_step_ids == sequence ids` (Codex #9 gate — drops cargo-cult evidence).
5. Output `gather-{date}.json`.

---

### Task 5.4: Phase 3 — Consolidate (merge in place)

**Files:**
- Modify: `bootstrap-consolidate.py` add `phase_consolidate()`
- Test: `tests/test_consolidate_merge.py`

**Logic:** For each rule with ≥5 attributed PASS samples + correctness ≥ 0.8 (reuses `bootstrap-shadow-evaluator.py`):
- Tier-A confirm → call `str_replace` on `overlay.yml` + `rules/{slug}.md` (MERGE, not append)
- Convert any relative dates in body to absolute
- Append entry to `CONSOLIDATION-LOG.md` (audit trail, append-only)

For rules with ≥3 attributed FAIL after PASS streak: emit `bootstrap.contradiction_detected`, append warning to `CONSOLIDATION-LOG.md`, NO auto-retract.

---

### Task 5.5: Phase 4 — Prune & Index

**Files:**
- Modify: `bootstrap-consolidate.py` add `phase_prune()`
- Test: `tests/test_consolidate_prune.py`

**Logic:**
- Rebuild `.vg/bootstrap/MEMORY.md` ≤ 200 lines (Anthropic actual): one-line entries pointing to `rules/{slug}.md`
- Demote verbose entries to `topics/{topic}.md`
- Update lock state, write `state.json` with `last_run_ts` + reset `sessions_since_last`
- Release `.consolidation.lock`

---

### Task 5.6: `/vg:learn --consolidate` mode

**Files:**
- Modify: `codex-skills/vg-learn/SKILL.md`
- Modify: `.codex/skills/vg-learn/SKILL.md`
- Modify: `commands/vg/learn.md`
- Test: `tests/test_learn_consolidate_mode.py`

**Logic:** New flag `--consolidate` invokes `bootstrap-consolidate.py` with all 4 phases. Output report to user. No auto-promote without `--apply`. Default: dry-run-only.

---

## Stage 6: Rollout flag + E2E

### Task 6.1: Add `meta_memory_mode` flag to vg.config.md template

**Files:**
- Modify: `commands/vg/_shared/config-loader.md`
- Modify: `vg.config.md` template (project init)
- Test: `tests/test_meta_memory_mode_flag.py`

**Allowed values:** `disabled` (default), `reflect-only`, `inject-as-advice`, `default`.

---

### Task 6.2: E2E loop test

**Files:**
- Create: `tests/e2e/test_meta_memory_loop.py`

**Scenario:**
1. Phase 1 fixture: deploy fly.io PASS sequence X
2. Run reflector → assert CANDIDATES.md grows
3. Promote candidate via `/vg:learn`
4. Phase 2 fixture: same env fingerprint
5. Run build preflight → assert `.build-context.md` contains rule
6. Run deploy → assert `bootstrap.rule_fired` emitted
7. Probe attribution → assert `executed_step_ids == sequence ids`
8. Repeat 3× → run consolidate → assert tier A confirmed, MEMORY.md updated

---

### Task 6.3: Causal misattribution regression test

**Files:**
- Create: `tests/e2e/test_no_cargo_cult.py`

**Scenario:** Promote rule, fire it, but executor BYPASSES sequence (different commands). Assert:
- `bootstrap.outcome_recorded` payload `attribution.executed_step_ids == []`
- Consolidator drops sample from shadow stats
- After 5 such bypasses, rule does NOT auto-promote despite phase-pass

---

### Task 6.4: Cross-platform smoke test (Windows)

**Files:**
- Create: `tests/smoke/test_windows_powershell_inject.py`

Verifies bootstrap-inject.sh under git-bash on Windows. Regression for codex Pencil MCP file-open dialog (separate fix in `~/.codex/config.toml`).

---

### Task 6.5: Documentation update

**Files:**
- Modify: `docs/plans/2026-05-08-meta-memory-design.md` add Section 14 "Implementation status"
- Modify: `CHANGELOG.md`
- Modify: `commands/vg/learn.md` (add --consolidate docs)

**Step 1-5:** Reflect what was built. Tag as v2.52 release candidate. Reference: `git tag v2.52-rc1`.

---

## Rollout sequence (production)

After all tasks complete:

1. Tag `v2.52-rc1`. Run regression suite.
2. Set `meta_memory_mode: reflect-only` on 1 dogfood phase. Verify CANDIDATES.md grows clean.
3. After 1 phase + manual review of candidates → flip to `inject-as-advice` on 3 phases × 2 env shapes (e.g., fly.io + render).
4. After 5 phases passing shadow evaluator (≥5 attributed samples each, correctness ≥ 0.8) → flip default `meta_memory_mode: default`.
5. Tag `v2.52` stable.

---

## DRY/YAGNI checks

- Reuse `bootstrap-loader.py`, `bootstrap-shadow-evaluator.py`, `bootstrap-inject.sh`, `bootstrap-conflict-detector.py` — no parallel infra.
- No new MCP server. Echo-chamber guard reuses reflector's existing user-msg + git-log channel + structured digest (NOT raw transcript).
- No cron auto-trigger in v1. User invokes `/vg:learn --consolidate`.
- No cross-project memory in v1 (Section 10 out-of-scope).

---

## References

- Design: `docs/plans/2026-05-08-meta-memory-design.md` (v1 + Section 13 verification)
- Anthropic Auto Dream: [claudefa.st](https://claudefa.st/blog/guide/mechanics/auto-dream)
- Memory Tool API: [platform.claude.com](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)
- Codex review evidence: commit `2f2bfb5` Section 13.2
- Existing infra:
  - `.claude/scripts/bootstrap-loader.py`
  - `.claude/scripts/bootstrap-shadow-evaluator.py`
  - `commands/vg/_shared/lib/bootstrap-inject.sh`
  - `commands/vg/_shared/reflection-trigger.md`
