# v2.66.0 — Plan-fidelity B1 + CrossAI hotfix bundle + Prereq strict default

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Ship B1 per-task spec compliance reviewer + close 6 GitHub issues (4 CRITICAL/HIGH crossai-runner infra + 2 CRITICAL prereq enforcement). Strict prereq default ON (BREAKING).

**Architecture:** B1 adds new spec-compliance reviewer step in build pipeline (modeled after existing L-gates). C4 flips lenient prereq verifier to strict default + scope step enforces upstream amendment when declaring cross-phase prereqs. C1 patches 4 crossai-runner bugs.

**Tech Stack:** Python 3 (orchestrator + verifiers + tests), Bash (crossai-runner shell), Markdown (commands + skill text).

**Issues closed:** #149 #150 #151 #152 #155 #156 (6 of 8 open). Remaining (#153 aggregator clustering, #154 marker semantics) deferred to v2.66.1.

---

## Context

User-confirmed scope choices:
1. v2.66.0 ~25h split-bundle: B1 + C4 + C1
2. C4 strict mode default ON (BREAKING) — match A7 pattern, fix at source

**Issue cluster origin (PrintwayV3 dogfood, 2026-05-09):**
- 31 runtime 404s on review smoke (cascade)
- Root cause: lenient prereq gate let blueprint+build pass with all upstream patches DEFERRED
- Conceptual cause: scope step doesn't enforce upstream amendment when declaring cross-phase prereqs
- Aggravating factor: CrossAI reviewers all returned `inconclusive` due to 4 separate runner infra bugs

**File targets located:** see research output. Key paths:
- `commands/vg/_shared/crossai-invoke.md:94-95` — pipe quoting (#149)
- `scripts/crossai-runner.py:126-128` — bare `replace()` (#149)
- `scripts/crossai-runner.py:163` — raw stdout write (#155)
- `scripts/crossai-normalize-results.py:21-28, 64-71` — failure classifier (#151)
- `commands/vg/_shared/crossai-invoke.md:93` — codex template missing flag (#150)
- `commands/vg/_shared/scope/completeness-validation.md:39, 236-241` — lenient default + exit 0 branch (#152)
- `commands/vg/scope.md:202-205` — Step 5 (no upstream amendment enforcement) (#156)
- `commands/vg/build.md:327-338` — STEP 5 model for B1 spec-reviewer wiring

VERSION baseline: 2.65.0. Bump to 2.66.0.

---

## Task 1 (C1.1): #149 — CrossAI runner path-quoting fix

**Files:**
- Modify: `commands/vg/_shared/crossai-invoke.md:93-95` (template strings)
- Modify: `scripts/crossai-runner.py:126-128` (bare `replace()` → shlex.quote substitution)
- Mirror: `.claude/commands/vg/_shared/crossai-invoke.md`, `.claude/scripts/crossai-runner.py`
- Test: `tests/test_crossai_runner_path_quoting.py` (NEW)

**Step 1: Failing test**

```python
"""v2.66.0 C1.1 (#149) — CrossAI runner path-quoting."""
import re
import subprocess
import tempfile
from pathlib import Path
import pytest


def test_path_with_spaces_in_context_arg():
    """Context path with spaces must be quoted in pipe invocation."""
    import sys
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    from crossai_runner import _materialize_command  # to be added or imported
    
    cmd = _materialize_command(
        template='cat {context} | claude --model sonnet -p "{prompt}"',
        context_path="/path with space/ctx.md",
        prompt="hello",
    )
    # Either single-quote or shlex.quote must wrap the path
    assert "'/path with space/ctx.md'" in cmd or '"/path with space/ctx.md"' in cmd, \
        f"Path with spaces not quoted: {cmd}"


def test_prompt_with_quotes_escaped():
    """Prompt containing quotes/special chars must not break shell parse."""
    import sys
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    from crossai_runner import _materialize_command
    
    cmd = _materialize_command(
        template='cat {context} | claude --model sonnet -p "{prompt}"',
        context_path="/tmp/ctx.md",
        prompt='hello "world" with $vars',
    )
    # The prompt value must end up shell-safe; assert no unescaped raw double quote
    # appears mid-arg (allow shlex's chosen quoting style)
    assert cmd.count('-p ') == 1
    # Run sh -n to validate syntax (POSIX shell parse check, not execute)
    rc = subprocess.run(["sh", "-n", "-c", cmd]).returncode
    assert rc == 0, f"Command not shell-safe: {cmd}"


def test_template_invoke_md_uses_quoted_form():
    """commands/vg/_shared/crossai-invoke.md must show {context} wrapped in shell quotes."""
    body = Path("commands/vg/_shared/crossai-invoke.md").read_text(encoding="utf-8")
    # Look for cat <unquoted>{context} pattern — must NOT exist
    bad = re.search(r"cat\s+\{context\}", body)
    assert not bad, f"Found unquoted cat {{context}} pattern in invoke template"
    # Must have either "'{context}'" or '"{context}"'
    assert re.search(r"cat\s+['\"]\{context\}['\"]", body), \
        "invoke template must wrap {context} in shell quotes"
```

**Step 2: Run → FAIL** (current bare `replace()` produces unquoted shell-unsafe paths)

**Step 3: Implement**

Add helper to `scripts/crossai-runner.py` near line 126:

```python
import shlex

def _materialize_command(template: str, context_path: str, prompt: str) -> str:
    """Substitute {context} and {prompt} with shell-safe quoted values."""
    return (
        template
        .replace("{context}", shlex.quote(str(context_path)))
        .replace("{prompt}", shlex.quote(str(prompt)))
    )
```

Replace `command_template.replace(...)` at line 126-128 with `_materialize_command(...)`.

Update `commands/vg/_shared/crossai-invoke.md:93-95` templates:
- Old: `cat {context} | claude --model sonnet -p "{prompt}"`
- New: `cat '{context}' | claude --model sonnet -p {prompt}`  (single-quote on context; shlex.quote on prompt produces own quoting)

Same change for codex + gemini templates on adjacent lines.

**Step 4: Run tests → PASS**

**Step 5: Mirror + commit**

```bash
git commit -m "fix(crossai): shlex.quote context path + prompt for path-with-spaces (#149)"
```

---

## Task 2 (C1.2): #150 — Codex CLI `--skip-git-repo-check` in invoke template

**Files:**
- Modify: `commands/vg/_shared/crossai-invoke.md:93` (codex template line)
- Mirror
- Test: `tests/test_crossai_codex_skip_git_check.py` (NEW)

**Step 1: Failing test**

```python
import re
from pathlib import Path


def test_codex_template_has_skip_git_repo_check():
    body = Path("commands/vg/_shared/crossai-invoke.md").read_text(encoding="utf-8")
    # Must include --skip-git-repo-check in the codex exec template
    codex_lines = [l for l in body.splitlines() if "codex exec" in l]
    assert codex_lines, "codex exec template not found"
    for line in codex_lines:
        assert "--skip-git-repo-check" in line, \
            f"Codex template missing --skip-git-repo-check: {line}"


def test_build_crossai_loop_keeps_flag():
    """vg-build-crossai-loop.py already has flag — regression guard."""
    body = Path("scripts/vg-build-crossai-loop.py").read_text(encoding="utf-8")
    assert "--skip-git-repo-check" in body
```

**Step 2: FAIL** (only build-crossai-loop has flag, not invoke template)

**Step 3: Edit `commands/vg/_shared/crossai-invoke.md:93`**:

Old: `codex exec "{prompt}"`
New: `codex exec --skip-git-repo-check --config sandbox_mode=read-only "{prompt}"`

(Match the build-crossai-loop config style for parity.)

**Step 4-5:** Mirror + commit.

```bash
git commit -m "fix(crossai): add --skip-git-repo-check to codex exec template (#150)"
```

---

## Task 3 (C1.3): #151 — Gemini cert error → actionable hint

**Files:**
- Modify: `scripts/crossai-normalize-results.py:21-28, 64-71` (add `tls_self_signed` pattern + actionable hint)
- Mirror: `.claude/scripts/crossai-normalize-results.py`
- Test: `tests/test_crossai_cert_error_classifier.py` (NEW)

**Step 1: Failing test**

```python
import sys
from pathlib import Path
import pytest


def _import_classifier():
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    return __import__("crossai_normalize_results")


def test_self_signed_cert_classified():
    """Gemini self-signed cert error must classify as tls_self_signed (not auth_missing)."""
    mod = _import_classifier()
    err_text = (
        'Error authenticating: _GaxiosError: request to '
        'https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist failed,\n'
        '  reason: self-signed certificate in certificate chain'
    )
    reason = mod._classify_failure(err_text, exit_code="1")
    assert reason == "tls_self_signed", \
        f"Expected tls_self_signed, got {reason!r}"


def test_no_active_credentials_still_auth_missing():
    """Regression guard: non-cert auth errors still classify as auth_missing."""
    mod = _import_classifier()
    err_text = "Error: no active credentials found. Run gemini auth login."
    reason = mod._classify_failure(err_text, exit_code="1")
    assert reason == "auth_missing"


def test_tls_hint_message_present():
    """Result file metadata must include actionable hint text for tls_self_signed."""
    mod = _import_classifier()
    # Hint may be in HINTS dict or applied at normalize-result time
    assert hasattr(mod, "FAILURE_HINTS") or hasattr(mod, "HINTS"), \
        "classifier must expose hint text mapping"
    hints = getattr(mod, "FAILURE_HINTS", None) or getattr(mod, "HINTS", {})
    assert "tls_self_signed" in hints
    hint_text = hints["tls_self_signed"]
    assert "NODE_EXTRA_CA_CERTS" in hint_text or "ca cert" in hint_text.lower() or \
           "self-signed" in hint_text.lower(), \
        f"Hint must mention CA cert workaround: {hint_text!r}"
```

**Step 2: FAIL**

**Step 3: Implement** in `scripts/crossai-normalize-results.py`:

```python
INFRA_PATTERNS = [
    # ... existing entries ...
    ("tls_self_signed", r"self.signed certificate|certificate chain|unable to verify the first certificate|SSL certificate problem"),
    ("auth_missing", r"no active credentials|error authenticating|authentication"),
    # ... rest ...
]

FAILURE_HINTS = {
    "tls_self_signed": (
        "TLS handshake failed (self-signed CA chain). On corp networks, "
        "set NODE_EXTRA_CA_CERTS=/path/to/corp-ca.pem before invoking gemini, "
        "OR pass --insecure-skip-tls-verify if your gemini build supports it."
    ),
    "auth_missing": "Run `gemini auth login` to refresh credentials.",
    # ... add hints for other reasons ...
}
```

In normalize_result writer, when reason matches, prepend `FAILURE_HINTS.get(reason, '')` to the failure_detail field.

**Step 4-5:** Mirror + commit.

```bash
git commit -m "fix(crossai): tls_self_signed classifier + CA cert hint for Gemini (#151)"
```

---

## Task 4 (C1.4): #155 — Codex banner XML pollution

**Files:**
- Modify: `scripts/crossai-runner.py:163` (banner-strip before write)
- Mirror
- Test: `tests/test_crossai_codex_banner_strip.py` (NEW)

**Step 1: Failing test**

```python
import sys
from pathlib import Path


def _import_runner():
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "scripts"))
    return __import__("crossai_runner")


def test_codex_banner_stripped_before_xml():
    """Codex banner lines must be stripped before writing result-codex-rN.xml."""
    mod = _import_runner()
    raw = (
        "Reading additional input from stdin...\n"
        "OpenAI Codex v0.118.0 (research preview)\n"
        "--------\n"
        "workdir: /tmp/x\n"
        "model: gpt-5.4\n"
        "provider: openai\n"
        "--------\n"
        "user\n"
        "<actual prompt>\n"
        "<crossai_review>\n"
        "  <verdict>ok</verdict>\n"
        "</crossai_review>\n"
    )
    cleaned = mod._strip_codex_banner(raw)
    # Must start with <crossai_review> or actual content, NOT banner
    assert cleaned.lstrip().startswith("<crossai_review>"), \
        f"Banner not stripped: {cleaned[:200]!r}"


def test_non_codex_output_unchanged():
    """Claude/Gemini outputs (no banner) must pass through unchanged."""
    mod = _import_runner()
    raw = "<crossai_review>\n  <verdict>ok</verdict>\n</crossai_review>\n"
    assert mod._strip_codex_banner(raw) == raw


def test_banner_only_content_yields_empty():
    """If output is ONLY banner (no actual model output), return empty/sentinel."""
    mod = _import_runner()
    raw = (
        "Reading additional input from stdin...\n"
        "OpenAI Codex v0.118.0 (research preview)\n"
        "--------\n"
        "workdir: /tmp/x\n"
        "--------\n"
    )
    cleaned = mod._strip_codex_banner(raw)
    # Cleaned content should be empty or whitespace-only
    assert not cleaned.strip(), f"Banner-only output should clean to empty: {cleaned!r}"
```

**Step 2: FAIL** (no `_strip_codex_banner` exists)

**Step 3: Implement** in `scripts/crossai-runner.py`:

```python
def _strip_codex_banner(text: str) -> str:
    """Strip Codex CLI banner lines before persisting to result file.
    
    Codex emits a banner ending with `--------` separator + `user` line + `<actual prompt>`
    before the model output begins. We strip everything up to (and including) the prompt
    echo line, leaving only the model's output.
    """
    if "OpenAI Codex" not in text:
        return text  # not a codex output — pass through
    
    lines = text.splitlines(keepends=True)
    # Find LAST `--------` separator + skip past `user` + `<actual prompt>` lines
    sep_indices = [i for i, l in enumerate(lines) if l.strip() == "--------"]
    if len(sep_indices) >= 2:
        # Banner ends at second separator. Skip 1 more line (the `user` keyword) +
        # any prompt echo lines until model output begins.
        start = sep_indices[-1] + 1
        # Skip "user" line if present
        if start < len(lines) and lines[start].strip() == "user":
            start += 1
        # Skip prompt echo lines (anything not starting with `<` xml or `{` json)
        while start < len(lines) and not lines[start].strip().startswith(("<", "{", "```")):
            start += 1
        return "".join(lines[start:])
    
    return text
```

Wire into `_write(result_file, _strip_codex_banner(stdout_text))` at line 163 area.

**Step 4-5:** Mirror + commit.

```bash
git commit -m "fix(crossai): strip Codex CLI banner before writing result XML (#155)"
```

---

## Task 5 (C4.1): #152 — Prereq verifier strict default ON (BREAKING)

**Files:**
- Modify: `commands/vg/_shared/scope/completeness-validation.md:39, 236-241` (flip default WARN→BLOCK + exit code logic)
- Add: `--lenient-prereqs` opt-out flag in `commands/vg/scope.md` argument parsing
- Mirror
- Test: `tests/test_prereq_strict_default.py` (NEW)

**Step 1: Failing test**

```python
import re
from pathlib import Path


def test_completeness_validation_strict_default():
    """v2.66.0 BREAKING: prereq fidelity default → BLOCK (was WARN since prior versions)."""
    body = Path("commands/vg/_shared/scope/completeness-validation.md").read_text(encoding="utf-8")
    # Old: "default (~0.85) → WARN"
    # New: "default → BLOCK; lenient (--lenient-prereqs flag) → WARN"
    bad = re.search(r"default.{0,20}→\s*WARN", body)
    assert not bad, f"Found stale default→WARN text: {bad.group(0) if bad else ''}"
    # Must mention strict-by-default
    assert re.search(r"strict.{0,30}default|default.{0,30}strict|default.{0,30}BLOCK", body, re.IGNORECASE), \
        "completeness-validation.md must declare strict default"


def test_warn_count_blocks_in_strict():
    """Exit code 1 when WARN_COUNT > 0 in strict default mode."""
    body = Path("commands/vg/_shared/scope/completeness-validation.md").read_text(encoding="utf-8")
    # Old: `if [ "$BLOCK_COUNT" -gt 0 ]; then ... exit 1`
    # New: in strict, both WARN and BLOCK trigger exit 1
    assert re.search(r"WARN_COUNT.*-gt\s+0", body) or \
           re.search(r"VIOLATION_COUNT.*-gt\s+0", body) or \
           re.search(r"strict.*exit\s+1", body, re.IGNORECASE), \
        "Strict mode must exit 1 when warnings present"


def test_lenient_opt_out_flag_documented():
    body = Path("commands/vg/scope.md").read_text(encoding="utf-8")
    assert "--lenient-prereqs" in body, "Must provide --lenient-prereqs opt-out flag"
```

**Step 2: FAIL**

**Step 3: Implement**

Edit `commands/vg/_shared/scope/completeness-validation.md`:
- Replace "default (~0.85) → WARN" with "**v2.66.0 BREAKING:** default → BLOCK. Use `--lenient-prereqs` flag for v2.65.x WARN behavior."
- Update exit-code logic block (lines 236-241):

```bash
if [ "${LENIENT_PREREQS:-false}" = "true" ]; then
    # Lenient mode (legacy v2.65.x behavior, opt-out via --lenient-prereqs flag)
    if [ "$BLOCK_COUNT" -gt 0 ]; then
        echo "⛔ ${BLOCK_COUNT} BLOCK violations" >&2
        exit 1
    fi
else
    # Strict mode (v2.66.0 default — both WARN and BLOCK trigger exit 1)
    if [ "$BLOCK_COUNT" -gt 0 ] || [ "$WARN_COUNT" -gt 0 ]; then
        echo "⛔ ${BLOCK_COUNT} BLOCK + ${WARN_COUNT} WARN violations (strict mode; use --lenient-prereqs to downgrade)" >&2
        exit 1
    fi
fi
```

Edit `commands/vg/scope.md` argument-hint and parse loop:
- Add `[--lenient-prereqs]` to argument-hint
- Add to parse loop: `--lenient-prereqs) LENIENT_PREREQS=true; export LENIENT_PREREQS ;;`

**Step 4-5:** Mirror + commit.

```bash
git commit -m "fix(scope): prereq strict default ON BREAKING + --lenient-prereqs opt-out (#152)"
```

---

## Task 6 (C4.2): #156 — Scope step enforces upstream amendment

**Files:**
- Modify: `commands/vg/scope.md:202-205` (Step 5 — add prereq enforcement check)
- Modify: `commands/vg/_shared/scope/completeness-validation.md` (add Check E — upstream owner phase verification)
- Modify: `codex-skills/vg-scope/SKILL.md` (mirror enforcement instruction)
- Mirror
- Test: `tests/test_scope_upstream_amendment_enforcement.py` (NEW)

**Step 1: Failing test**

```python
import re
from pathlib import Path


def test_scope_step5_mentions_upstream_amendment():
    body = Path("commands/vg/scope.md").read_text(encoding="utf-8")
    # Step 5 must reference upstream amendment requirement
    assert re.search(r"upstream\s+amendment|owner\s+phase.*amendment|prerequisite.*owner", body, re.IGNORECASE), \
        "scope.md Step 5 must enforce upstream amendment for cross-phase prereqs"


def test_completeness_check_e_exists():
    body = Path("commands/vg/_shared/scope/completeness-validation.md").read_text(encoding="utf-8")
    # Must add new Check E (or named "Upstream Prereq Verification")
    assert re.search(r"Check\s+E|upstream\s+prereq", body, re.IGNORECASE), \
        "completeness-validation.md must add Check E for upstream prereq verification"


def test_check_e_blocks_when_owner_missing():
    """Check E must BLOCK when prereq table references owner phase that hasn't scoped the field/endpoint."""
    body = Path("commands/vg/_shared/scope/completeness-validation.md").read_text(encoding="utf-8")
    # The check logic must call grep/scan on owner phase SPECS.md or PLAN.md
    assert re.search(r"owner.*SPECS\.md|owner.*PLAN\.md|grep.*owner.*phase", body, re.IGNORECASE | re.DOTALL), \
        "Check E must scan owner phase artifacts for prereq fields/endpoints"


def test_check_e_demands_amendment_when_missing():
    body = Path("commands/vg/_shared/scope/completeness-validation.md").read_text(encoding="utf-8")
    # Failure path must mention /vg:amend or insertion of patch phase
    assert re.search(r"/vg:amend|patch\s+phase|amend.*owner", body, re.IGNORECASE), \
        "Check E failure must point to /vg:amend or patch phase remedy"


def test_codex_scope_skill_mirrors_enforcement():
    body = Path("codex-skills/vg-scope/SKILL.md").read_text(encoding="utf-8")
    # Codex skill must mention same enforcement (or reference completeness-validation.md)
    assert "upstream" in body.lower() or "Check E" in body or "amend" in body.lower()
```

**Step 2: FAIL**

**Step 3: Implement**

Add new section to `commands/vg/_shared/scope/completeness-validation.md` after existing checks:

```markdown
### Check E — Upstream Prereq Verification (v2.66.0 #156)

When CONTEXT.md declares a `Prerequisites:` table referencing fields/endpoints owned by upstream phases (cross-phase prereqs), Check E verifies each entry exists in the owner phase's SPECS.md or PLAN.md before allowing scope to complete.

**Logic:**

```bash
PREREQS_TABLE=$(grep -A 100 "^## Prerequisites" "${PHASE_DIR}/CONTEXT.md" 2>/dev/null | head -100)
if [ -n "$PREREQS_TABLE" ]; then
    while IFS='|' read -r _ owner_phase artifact symbol _; do
        owner_phase=$(echo "$owner_phase" | xargs)
        symbol=$(echo "$symbol" | xargs)
        [ -z "$owner_phase" ] && continue
        [ -z "$symbol" ] && continue
        
        owner_specs=".vg/phases/${owner_phase}/SPECS.md"
        owner_plan=".vg/phases/${owner_phase}/PLAN.md"
        
        # Search for symbol in owner phase artifacts
        found=false
        if [ -f "$owner_specs" ] && grep -q "$symbol" "$owner_specs"; then found=true; fi
        if [ -f "$owner_plan" ] && grep -q "$symbol" "$owner_plan"; then found=true; fi
        
        if [ "$found" = "false" ]; then
            VIOLATIONS+=("Check E BLOCK: prereq '${symbol}' not found in owner phase ${owner_phase}. Run \`/vg:amend ${owner_phase}\` to add it OR insert a patch phase before this scope completes.")
            BLOCK_COUNT=$((BLOCK_COUNT + 1))
        fi
    done <<< "$PREREQS_TABLE"
fi
```

**Failure remedy:** Operator must either:
1. Run `/vg:amend ${owner_phase}` to add the missing field/endpoint to owner's SPECS/PLAN
2. Insert a patch phase (e.g. `${owner_phase}.5`) before this phase
3. Remove the prereq from CONTEXT.md if the symbol is actually local

**Why strict (no `--lenient-prereqs` exemption for Check E):** Lenient mode covers fidelity score for design refs. Cross-phase prereqs declaring missing upstream symbols ARE the cascade root cause — there's no legitimate reason to lenient-skip a missing upstream patch.
```

Edit `commands/vg/scope.md:202-205` (Step 5 description):

```markdown
**Check E (v2.66.0):** Upstream prereq verification — when CONTEXT.md declares `Prerequisites:` table with owner_phase + symbol entries, each symbol must exist in owner's SPECS.md or PLAN.md. Missing → BLOCK + remedy via `/vg:amend ${owner_phase}` or patch phase. Cannot be `--lenient-prereqs` exempted.
```

Edit `codex-skills/vg-scope/SKILL.md` (add brief enforcement note):

```markdown
**Check E enforcement (v2.66.0):** When you author Prerequisites: in CONTEXT.md, every owner_phase + symbol pair MUST already exist in owner SPECS.md/PLAN.md. If owner missing, STOP and propose `/vg:amend ${owner_phase}` before continuing scope.
```

**Step 4-5:** Mirror + commit.

```bash
git commit -m "fix(scope): Check E upstream prereq enforcement BREAKING (#156)"
```

---

## Task 7 (B1): Per-task spec compliance reviewer

**Files:**
- Create: `.claude/agents/vg-build-spec-reviewer/SKILL.md` (NEW agent definition)
- Modify: `commands/vg/_shared/build/post-execution-overview.md` (add B1 reviewer step)
- Modify: `commands/vg/build.md:327-338` (wire B1 spawn after L gates)
- Mirror
- Test: `tests/test_b1_spec_reviewer.py` (NEW)

**Step 1: Failing tests**

```python
import re
from pathlib import Path


def test_spec_reviewer_agent_exists():
    """v2.66.0 B1 — new vg-build-spec-reviewer agent definition exists."""
    p = Path(".claude/agents/vg-build-spec-reviewer/SKILL.md")
    assert p.exists(), "vg-build-spec-reviewer agent definition missing"
    body = p.read_text(encoding="utf-8")
    assert "spec compliance" in body.lower() or "spec-compliance" in body
    assert "PLAN.md" in body  # must reference plan as source of truth


def test_build_post_execution_invokes_spec_reviewer():
    body = Path("commands/vg/_shared/build/post-execution-overview.md").read_text(encoding="utf-8")
    assert "vg-build-spec-reviewer" in body, \
        "post-execution-overview must spawn vg-build-spec-reviewer per task"


def test_build_md_wires_b1_step():
    body = Path("commands/vg/build.md").read_text(encoding="utf-8")
    # B1 must be wired in STEP 5 or new sub-step
    assert "spec-reviewer" in body or "spec_reviewer" in body or \
           "vg-build-spec-reviewer" in body, \
        "build.md must reference B1 spec reviewer wiring"


def test_spec_reviewer_per_task_not_per_wave():
    """B1 reviews per-task, not per-wave (each task gets independent compliance check)."""
    p = Path(".claude/agents/vg-build-spec-reviewer/SKILL.md")
    body = p.read_text(encoding="utf-8")
    assert "per task" in body.lower() or "per-task" in body
```

**Step 2: FAIL**

**Step 3: Create agent definition** `.claude/agents/vg-build-spec-reviewer/SKILL.md`:

```markdown
---
name: vg-build-spec-reviewer
description: |
  Per-task spec compliance reviewer. Reads PLAN.md task spec + commit diff
  for the task, verifies code matches plan exactly. NOT a code quality
  reviewer (separate concern). Returns PASS/FAIL with specific gaps.
allowed-tools:
  - Read
  - Bash
  - Grep
---

# vg-build-spec-reviewer

You are a spec compliance reviewer for v2.66.0 B1. Strictly verify code matches plan; do NOT review code quality.

## Input

- `task_id` — task ID from PLAN.md (e.g. "task-15", "A3")
- `commit_sha` — commit SHA produced by the implementer subagent
- `phase_dir` — phase artifact directory containing PLAN.md

## Job

1. Read PLAN.md task block matching `task_id`
2. Run `git show <commit_sha>` to inspect actual changes
3. For each requirement in plan:
   - REQUIRED items present? (file paths, function signatures, behavior)
   - FORBIDDEN items absent? (no scope creep, no version bumps if not the release task)
4. For each test mandated by plan: confirm test file exists with required assertions
5. Output structured verdict: PASS or FAIL + specific gaps + file:line evidence

## Output format

```
## Spec Compliance — {task_id}

### Required items
- [✅/❌] {item}: {evidence at file:line}

### Forbidden items
- [✅/❌] {item}: {evidence}

### Verdict
PASS | FAIL — {one-line summary}

### If FAIL — exact gaps
1. {gap 1 with file:line + remediation}
```

## Strict rules

- "Close enough" = FAIL
- Missing test = FAIL even if implementation looks correct
- Extra functionality not in plan = FAIL (scope creep)
- Skip code quality issues — those are reviewed by a separate quality reviewer
- Be lenient on naming (e.g. `parallel` vs `parallel_workers` arg name) when intent matches
- Be strict on principle (e.g. error-shape homogeneity, default values, mirror byte-identity)

This is a per-task gate. Run independently for every implemented task before marking it complete.
```

**Wire in build.md:**

After STEP 5 post-execution gate (line 327-338), ADD STEP 5.1:

```markdown
### STEP 5.1 — B1 per-task spec compliance review (v2.66.0)

For each task in current wave that produced commits, spawn vg-build-spec-reviewer:

```bash
for task_id in "${WAVE_TASKS[@]}"; do
  COMMIT_SHA=$(git log --grep="task-${task_id}\\|${task_id}:" -n1 --format=%H)
  bash scripts/vg-narrate-spawn.sh vg-build-spec-reviewer spawning "spec-review task-${task_id}"
  # Then: Agent(subagent_type="vg-build-spec-reviewer", prompt=<rendered with task_id, commit_sha, phase_dir>)
done
```

Each spec-reviewer return: PASS or FAIL. On FAIL, route to in-scope-fix-loop OR re-spawn implementer per the existing fix protocol.

Marker: `5_1_spec_compliance_review` (severity: warn — informational signal, not a hard block, since fix protocol handles failures).
```

**Step 4-5:** Mirror + commit.

```bash
git commit -m "feat(build): B1 per-task spec compliance reviewer agent + wiring (v2.66.0)"
```

---

## Task 8: VERSION + CHANGELOG + tag + push

**Files:**
- Modify: `VERSION` (2.65.0 → 2.66.0)
- Modify: `package.json`
- Modify: `CHANGELOG.md` (prepend v2.66.0 entry)

**CHANGELOG entry:**

```markdown
## v2.66.0 — Plan-fidelity B1 + CrossAI hotfix bundle + Prereq strict (2026-05-09)

### Breaking changes
- **C4 #152 #156:** Prereq verifier strict default ON. Was lenient by default → cascade of 31 runtime 404s when upstream patches DEFERRED. Opt-out via `--lenient-prereqs` flag. Strict-only Check E (upstream prereq verification) cannot be lenient-exempted.

### Bug fixes (closes 6 GitHub issues from PrintwayV3 dogfood)
- **#149 CRITICAL:** crossai-runner path quoting — workspace path with spaces broke stdin pipe to all CLIs. Now uses `shlex.quote()` for context + prompt substitution.
- **#150 HIGH:** Codex CLI invoke template missing `--skip-git-repo-check` — added flag + sandbox config to match build-crossai-loop.
- **#151 HIGH:** Gemini self-signed cert error swallowed as `auth_missing` — new `tls_self_signed` classifier + actionable hint pointing to `NODE_EXTRA_CA_CERTS` workaround.
- **#152 CRITICAL:** Lenient prereq gate — flipped to strict default (BREAKING).
- **#155 LOW:** Codex banner text leaked into result XML — strip Codex CLI banner (everything before second `--------` separator + prompt echo) before persisting.
- **#156 CRITICAL:** Scope step doesn't enforce upstream amendment for cross-phase prereqs — added Check E (BLOCK) that scans owner phase SPECS.md/PLAN.md for declared prereq symbols. Missing → demand `/vg:amend ${owner_phase}` or patch phase before continuing.

### Features
- **B1:** Per-task spec compliance reviewer — new `.claude/agents/vg-build-spec-reviewer/SKILL.md` agent invoked after L-gates per implemented task. Strictly verifies code matches PLAN.md spec (separate from code quality). Wired in build STEP 5.1.

### Test coverage
**18+ new tests across 7 suites.** All pass.

### Migration
- **C4 breaking (BREAKING):** Existing scope steps without `--lenient-prereqs` will now BLOCK on prereq violations. To preserve v2.65.x behavior, pass `--lenient-prereqs` per invocation. Cannot lenient-exempt Check E (upstream prereq verification) — must run `/vg:amend ${owner_phase}` or insert patch phase.
- **B1 informational:** Default severity=warn. New per-task reviewer runs but doesn't block until v2.67.0 telemetry-driven flip.

### Deferred to v2.66.1
- **#153** review aggregator clustering by API contract
- **#154** crossai_review.done marker semantics
- **B2-B4** remaining plan-fidelity (questions+self-review, TDD plan structure, in-build final reviewer)
```

**Steps:**
1. Bump VERSION + package.json
2. Prepend CHANGELOG entry
3. Commit: `release: v2.66.0 — plan-fidelity B1 + crossai hotfix + prereq strict`
4. Tag `v2.66.0`
5. Push origin main + tag
6. `gh release create v2.66.0 ...`
7. Close issues #149 #150 #151 #152 #155 #156 with reference to v2.66.0 release

---

## Verification before complete

After each task:
- pytest pass for new tests
- mirror byte-identity verified
- existing tests still pass

After Task 8:
- `git log --oneline | head -10` shows 8 commits
- `cat VERSION` = `2.66.0`
- All 7 new test files pass
- 6 GitHub issues closed

---

## Execution mode

Subagent-driven development this session. Per task: implementer (questions → impl → tests → self-review → commit) → spec reviewer (use B1 agent if landed, else generic) → quality reviewer → mark complete. Final reviewer for entire delta before release tag.

C4 tasks (5+6) are BREAKING — prioritize spec review carefully. C1 tasks (1-4) are infra patches with clear targets — fast turnaround.
