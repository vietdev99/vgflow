# Batch 20 — Deploy contract lock + hook (URGENT — Ansible drift fix) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Project-agnostic deploy lock. Eliminate AI drift inventing wrong deploy commands across phases.

**Real bug (PrintwayV3):** Phase 3+ deployed via Ansible successfully. Different phase at /vg:test step → AI invented different deploy method instead of using ansible-playbook. No enforcement that AI uses canonical project deploy spec.

**Architecture:**
1. `.vg/DEPLOY-CONTRACT.json` — single source of truth per project
2. Init script bootstraps contract from `vg.config.md` or asks user on first deploy
3. Load script exports `$DEPLOY_BUILD/$DEPLOY_RESTART/$DEPLOY_HEALTH` env vars
4. PreToolUse Bash hook pattern-matches deploy commands; BLOCK if drift from contract fingerprint
5. All deploy steps source the load script before any deploy bash
6. Override path via `/vg:override-resolve --deploy-method` (logs override-debt)

**Tech Stack:** Python + bash (Windows + Unix compatible).

**Working directory:** `main`.

---

## Conventions

- Mirror byte-identical to `.claude/`
- Sweep: `python -m pytest tests/ -q --tb=no -k "deploy_contract or deploy_drift or batch_20"`
- Single Co-Authored-By trailer per commit

---

## Task 1: deploy-contract-init.py + deploy-contract-load.py

**Files:**
- Create: `scripts/deploy-contract-init.py`
- Create: `scripts/deploy-contract-load.py`
- Create: `schemas/deploy-contract.schema.json` (JSON schema)
- Mirrors
- Test: `tests/test_deploy_contract_scripts.py`

**Step 1: Failing test**

```python
"""tests/test_deploy_contract_scripts.py — Batch 20 deploy contract scripts."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
INIT = REPO / "scripts" / "deploy-contract-init.py"
LOAD = REPO / "scripts" / "deploy-contract-load.py"
SCHEMA = REPO / "schemas" / "deploy-contract.schema.json"


def test_scripts_exist():
    assert INIT.is_file(), "scripts/deploy-contract-init.py must ship"
    assert LOAD.is_file(), "scripts/deploy-contract-load.py must ship"
    assert SCHEMA.is_file(), "schemas/deploy-contract.schema.json must ship"


def test_init_bootstrap_from_explicit_args(tmp_path):
    """--method ansible --restart-cmd '...' bootstraps non-interactively."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    r = subprocess.run(
        [sys.executable, str(INIT),
         "--vg-dir", str(vg_dir),
         "--method", "ansible",
         "--pre", "git push origin main",
         "--build", "ansible-playbook deploy.yml --tags build -e env={env}",
         "--restart", "ansible-playbook deploy.yml --tags restart -e env={env}",
         "--health", "ansible-playbook health.yml -e env={env}",
         "--phase", "3"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"init failed: {r.stderr}"
    contract = vg_dir / "DEPLOY-CONTRACT.json"
    assert contract.is_file()
    data = json.loads(contract.read_text(encoding="utf-8"))
    assert data["method"] == "ansible"
    assert "ansible-playbook" in data["commands"]["build"]
    assert "fingerprint_pattern" in data
    assert "lock_sha256" in data


def test_init_idempotent(tmp_path):
    """Second init when contract exists must NOT overwrite without --force."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    contract = vg_dir / "DEPLOY-CONTRACT.json"
    contract.write_text(json.dumps({"method": "pm2", "commands": {"restart": "pm2 restart all"}, "fingerprint_pattern": "^pm2 ", "lock_sha256": "abc"}), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(INIT),
         "--vg-dir", str(vg_dir),
         "--method", "ansible",
         "--build", "x", "--restart", "y", "--health", "z",
         "--phase", "5"],
        capture_output=True, text=True,
    )
    # Without --force, should not overwrite
    assert r.returncode != 0 or "already" in (r.stdout + r.stderr).lower()
    data = json.loads(contract.read_text(encoding="utf-8"))
    assert data["method"] == "pm2"  # unchanged


def test_load_exports_env_vars(tmp_path):
    """Load script prints env-var assignments for sourcing."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    contract = vg_dir / "DEPLOY-CONTRACT.json"
    contract.write_text(json.dumps({
        "method": "ansible",
        "commands": {
            "pre": "git push",
            "build": "ansible-playbook build.yml -e env={env}",
            "restart": "ansible-playbook restart.yml -e env={env}",
            "health": "ansible-playbook health.yml -e env={env}",
            "rollback": "ansible-playbook rollback.yml -e env={env}",
        },
        "fingerprint_pattern": "^ansible-playbook ",
        "lock_sha256": "abc",
    }), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(LOAD),
         "--vg-dir", str(vg_dir),
         "--env", "sandbox"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"load failed: {r.stderr}"
    out = r.stdout
    assert "export DEPLOY_METHOD=" in out and "ansible" in out
    assert "export DEPLOY_BUILD=" in out
    assert "env=sandbox" in out  # placeholder substituted
    assert "export DEPLOY_FINGERPRINT_PATTERN=" in out


def test_load_blocks_when_contract_missing(tmp_path):
    """Missing contract → exit 1 with bootstrap hint."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    r = subprocess.run(
        [sys.executable, str(LOAD),
         "--vg-dir", str(vg_dir),
         "--env", "sandbox"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "DEPLOY-CONTRACT.json" in combined
    assert ("init" in combined.lower() or "bootstrap" in combined.lower())
```

**Step 2: Run** → 5 fail.

**Step 3: Implement**

Create `schemas/deploy-contract.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "title": "VGFlow Deploy Contract",
  "type": "object",
  "required": ["method", "commands", "fingerprint_pattern", "lock_sha256"],
  "properties": {
    "method": {
      "type": "string",
      "enum": ["ansible", "pm2", "docker", "systemd", "kubectl", "helm", "terraform", "capistrano", "fabric", "custom"]
    },
    "commands": {
      "type": "object",
      "required": ["build", "restart", "health"],
      "properties": {
        "pre": {"type": "string"},
        "build": {"type": "string"},
        "restart": {"type": "string"},
        "health": {"type": "string"},
        "rollback": {"type": "string"}
      }
    },
    "fingerprint_pattern": {"type": "string", "description": "Regex matching all valid deploy commands for drift detection"},
    "lock_sha256": {"type": "string"},
    "established_at": {"type": "string"},
    "established_by_phase": {"type": "string"},
    "established_by_run_id": {"type": "string"}
  }
}
```

Create `scripts/deploy-contract-init.py`:

```python
#!/usr/bin/env python3
"""deploy-contract-init.py — Batch 20

Bootstrap .vg/DEPLOY-CONTRACT.json on first deploy.

Modes:
  - Explicit args: --method ansible --build "..." --restart "..." --health "..."
  - From vg.config.md: auto-infer from deploy_profile + environments[env].deploy
  - Interactive: prompts user (when called from /vg:test or /vg:deploy with no flags)

Idempotent: refuses overwrite unless --force.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


VALID_METHODS = ["ansible", "pm2", "docker", "systemd", "kubectl",
                 "helm", "terraform", "capistrano", "fabric", "custom"]

# Heuristic patterns for auto-detecting method from command
METHOD_PATTERNS = {
    "ansible": r"^ansible(-playbook)?\b",
    "pm2": r"^pm2\b",
    "docker": r"^docker(\s+compose)?\b",
    "systemd": r"^sudo\s+systemctl\b|^systemctl\b",
    "kubectl": r"^kubectl\b",
    "helm": r"^helm\b",
    "terraform": r"^terraform\b",
    "capistrano": r"^cap\b|^bundle exec cap\b",
    "fabric": r"^fab\b",
}


def _infer_method(cmd: str) -> str:
    for method, pat in METHOD_PATTERNS.items():
        if re.search(pat, cmd):
            return method
    return "custom"


def _fingerprint_pattern(method: str) -> str:
    return METHOD_PATTERNS.get(method, r".*")


def _compute_lock_sha(commands: dict) -> str:
    canonical = json.dumps(commands, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vg-dir", type=Path, default=Path(".vg"))
    ap.add_argument("--method", choices=VALID_METHODS)
    ap.add_argument("--pre", default="")
    ap.add_argument("--build")
    ap.add_argument("--restart")
    ap.add_argument("--health")
    ap.add_argument("--rollback", default="")
    ap.add_argument("--phase", default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing contract (logs override-debt)")
    args = ap.parse_args()

    contract_path = args.vg_dir / "DEPLOY-CONTRACT.json"
    if contract_path.exists() and not args.force:
        existing = json.loads(contract_path.read_text(encoding="utf-8"))
        print(f"⛔ DEPLOY-CONTRACT.json already exists (method={existing.get('method')}).", file=sys.stderr)
        print(f"   Use --force to overwrite OR /vg:override-resolve --deploy-method to change", file=sys.stderr)
        return 1

    if not (args.build and args.restart and args.health):
        print("ERROR: --build, --restart, --health all required (or use interactive mode via /vg:deploy)", file=sys.stderr)
        return 2

    method = args.method or _infer_method(args.build)
    commands = {
        "pre": args.pre,
        "build": args.build,
        "restart": args.restart,
        "health": args.health,
        "rollback": args.rollback,
    }
    contract = {
        "method": method,
        "commands": commands,
        "fingerprint_pattern": _fingerprint_pattern(method),
        "lock_sha256": _compute_lock_sha(commands),
        "established_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "established_by_phase": args.phase,
        "established_by_run_id": args.run_id,
    }

    args.vg_dir.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    print(f"✓ DEPLOY-CONTRACT.json written: method={method}")
    print(f"  fingerprint_pattern={contract['fingerprint_pattern']}")
    print(f"  lock_sha256={contract['lock_sha256'][:12]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `scripts/deploy-contract-load.py`:

```python
#!/usr/bin/env python3
"""deploy-contract-load.py — Batch 20

Load .vg/DEPLOY-CONTRACT.json and print shell `export` statements for sourcing.

Usage in deploy step:
  eval "$(python scripts/deploy-contract-load.py --vg-dir .vg --env sandbox)"
  run_on_target "$DEPLOY_BUILD"

BLOCKs (exit 1) if contract missing — forces operator to run init first.
"""
from __future__ import annotations
import argparse
import json
import shlex
import sys
from pathlib import Path


def _substitute(cmd: str, env: str) -> str:
    return cmd.replace("{env}", env)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vg-dir", type=Path, default=Path(".vg"))
    ap.add_argument("--env", required=True)
    args = ap.parse_args()

    contract_path = args.vg_dir / "DEPLOY-CONTRACT.json"
    if not contract_path.is_file():
        print(f"⛔ DEPLOY-CONTRACT.json missing at {contract_path}", file=sys.stderr)
        print("   Bootstrap with one of:", file=sys.stderr)
        print("     /vg:deploy --init                                    # interactive", file=sys.stderr)
        print("     python scripts/deploy-contract-init.py \\", file=sys.stderr)
        print("       --method ansible --build '...' --restart '...' --health '...'", file=sys.stderr)
        return 1

    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⛔ DEPLOY-CONTRACT.json malformed: {e}", file=sys.stderr)
        return 1

    method = contract.get("method", "")
    cmds = contract.get("commands", {})
    fp = contract.get("fingerprint_pattern", "")
    lock = contract.get("lock_sha256", "")

    exports = {
        "DEPLOY_METHOD": method,
        "DEPLOY_PRE": _substitute(cmds.get("pre", ""), args.env),
        "DEPLOY_BUILD": _substitute(cmds.get("build", ""), args.env),
        "DEPLOY_RESTART": _substitute(cmds.get("restart", ""), args.env),
        "DEPLOY_HEALTH": _substitute(cmds.get("health", ""), args.env),
        "DEPLOY_ROLLBACK": _substitute(cmds.get("rollback", ""), args.env),
        "DEPLOY_FINGERPRINT_PATTERN": fp,
        "DEPLOY_CONTRACT_LOCK_SHA256": lock,
    }
    for key, val in exports.items():
        if val:
            print(f"export {key}={shlex.quote(val)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Step 4-6:** pass + mirror + commit.

```bash
git add scripts/deploy-contract-init.py scripts/deploy-contract-load.py \
        schemas/deploy-contract.schema.json \
        .claude/scripts/deploy-contract-init.py .claude/scripts/deploy-contract-load.py \
        .claude/schemas/deploy-contract.schema.json \
        tests/test_deploy_contract_scripts.py
git commit -m "feat(deploy): Batch 20 Task 1 — deploy-contract-init + load scripts

Canonical .vg/DEPLOY-CONTRACT.json per project. method ∈ {ansible, pm2,
docker, systemd, kubectl, helm, terraform, capistrano, fabric, custom}.

init: bootstrap from explicit flags. Auto-infers method from build command
pattern. Idempotent (refuses overwrite without --force).

load: reads contract, prints shell export DEPLOY_METHOD=...,
DEPLOY_BUILD=..., DEPLOY_RESTART=..., DEPLOY_HEALTH=...,
DEPLOY_FINGERPRINT_PATTERN=... for sourcing. {env} placeholder
substituted from --env arg.

Schema at schemas/deploy-contract.schema.json.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: PreToolUse Bash hook — deploy command drift guard

**Files:**
- Create: `scripts/hooks/vg-deploy-contract-guard.sh`
- Modify: `.claude/settings.json` (add PreToolUse Bash hook entry — via install-hooks.sh template)
- Modify: `scripts/hooks/install-hooks.sh` (wire the new hook)
- Mirror
- Test: `tests/test_deploy_contract_hook.py`

**Step 1: Failing test**

```python
"""tests/test_deploy_contract_hook.py — Batch 20 PreToolUse drift guard."""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts" / "hooks" / "vg-deploy-contract-guard.sh"
INSTALL = REPO / "scripts" / "hooks" / "install-hooks.sh"


def test_hook_exists():
    assert HOOK.is_file()


def test_hook_blocks_command_drift(tmp_path, monkeypatch):
    """Contract = ansible. AI tries 'pm2 restart all'. Hook BLOCKs."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    (vg_dir / "DEPLOY-CONTRACT.json").write_text(json.dumps({
        "method": "ansible",
        "commands": {"build": "ansible-playbook x", "restart": "ansible-playbook y", "health": "ansible-playbook z"},
        "fingerprint_pattern": "^ansible(-playbook)?\\b",
        "lock_sha256": "abc",
    }), encoding="utf-8")

    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "pm2 restart all"},
    })
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    r = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, env=env,
        capture_output=True, text=True,
    )
    # Hook must block — non-zero exit OR emit decision=block in stdout JSON
    blocked = r.returncode != 0 or '"decision": "block"' in r.stdout or '"decision":"block"' in r.stdout
    assert blocked, (
        f"Hook must BLOCK pm2 command when contract locked to ansible. "
        f"rc={r.returncode}, stdout={r.stdout[:200]}, stderr={r.stderr[:200]}"
    )


def test_hook_allows_matching_command(tmp_path):
    """ansible-playbook command must pass when contract = ansible."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    (vg_dir / "DEPLOY-CONTRACT.json").write_text(json.dumps({
        "method": "ansible",
        "commands": {"build": "ansible-playbook x", "restart": "ansible-playbook y", "health": "ansible-playbook z"},
        "fingerprint_pattern": "^ansible(-playbook)?\\b",
        "lock_sha256": "abc",
    }), encoding="utf-8")

    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "ansible-playbook deploy.yml --tags restart"},
    })
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    r = subprocess.run(
        ["bash", str(HOOK)],
        input=payload, env=env,
        capture_output=True, text=True,
    )
    # Exit 0, no decision=block
    assert r.returncode == 0, f"Hook should pass matching command, rc={r.returncode}"
    assert '"decision": "block"' not in r.stdout


def test_hook_passes_through_non_deploy_commands(tmp_path):
    """Non-deploy commands (npm test, git status, etc.) must pass through."""
    vg_dir = tmp_path / ".vg"
    vg_dir.mkdir()
    (vg_dir / "DEPLOY-CONTRACT.json").write_text(json.dumps({
        "method": "ansible",
        "commands": {"build": "ansible-playbook x", "restart": "ansible-playbook y", "health": "ansible-playbook z"},
        "fingerprint_pattern": "^ansible(-playbook)?\\b",
        "lock_sha256": "abc",
    }), encoding="utf-8")
    for cmd in ["npm test", "git status", "ls -la", "python script.py"]:
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        r = subprocess.run(["bash", str(HOOK)], input=payload, env=env,
                          capture_output=True, text=True)
        assert r.returncode == 0, f"non-deploy '{cmd}' should pass, rc={r.returncode}"


def test_install_hooks_wires_deploy_guard():
    body = INSTALL.read_text(encoding="utf-8")
    assert "vg-deploy-contract-guard" in body, (
        "install-hooks.sh must register vg-deploy-contract-guard.sh as "
        "PreToolUse Bash hook"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

Create `scripts/hooks/vg-deploy-contract-guard.sh`:

```bash
#!/usr/bin/env bash
# vg-deploy-contract-guard.sh — Batch 20 PreToolUse Bash hook
#
# Detects deploy-like commands and validates them against
# .vg/DEPLOY-CONTRACT.json fingerprint_pattern. BLOCKs on drift.
#
# Hook protocol: reads JSON from stdin, exit 0 to allow, exit non-zero
# OR emit {"decision":"block"} JSON to stdout to block.

set -uo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
CONTRACT="${PROJECT_DIR}/.vg/DEPLOY-CONTRACT.json"

# Read tool payload
INPUT=$(cat)

# Extract command via Python (jq may not exist on Windows)
CMD=$(${PYTHON_BIN:-python3} -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    if d.get('tool_name') != 'Bash':
        print('__SKIP__')
    else:
        print(d.get('tool_input', {}).get('command', ''))
except Exception:
    print('__SKIP__')
" <<<"$INPUT")

# Skip if not a Bash tool call
[ "$CMD" = "__SKIP__" ] && exit 0
[ -z "$CMD" ] && exit 0

# Deploy-like pattern detection (broad — covers common deploy tools)
DEPLOY_PATTERNS='(^|[[:space:]]|[;&|])(ansible(-playbook)?|pm2[[:space:]]+(start|restart|reload|stop)|docker[[:space:]]+compose|kubectl[[:space:]]+(apply|rollout|delete)|helm[[:space:]]+(install|upgrade|rollback)|terraform[[:space:]]+(apply|destroy)|sudo[[:space:]]+systemctl[[:space:]]+(restart|reload|start|stop)|capistrano|cap[[:space:]]+deploy|bundle[[:space:]]+exec[[:space:]]+cap|fab[[:space:]]+deploy)[[:space:]]'

if ! echo "$CMD " | grep -qE "$DEPLOY_PATTERNS"; then
  # Not a deploy command — pass through
  exit 0
fi

# Deploy command detected — check contract
if [ ! -f "$CONTRACT" ]; then
  cat <<EOF
{"decision":"block","reason":"Deploy command detected ('${CMD:0:80}...') but .vg/DEPLOY-CONTRACT.json missing. Bootstrap first with: python scripts/deploy-contract-init.py --method <ansible|pm2|docker|...> --build '...' --restart '...' --health '...'  OR run /vg:deploy --init for interactive bootstrap."}
EOF
  exit 0
fi

# Read fingerprint_pattern
FINGERPRINT=$(${PYTHON_BIN:-python3} -c "
import json
print(json.load(open('${CONTRACT}', encoding='utf-8')).get('fingerprint_pattern', ''))
" 2>/dev/null)

if [ -z "$FINGERPRINT" ]; then
  exit 0  # malformed contract — let other validators catch
fi

# Match command against fingerprint
if echo "$CMD" | grep -qE "$FINGERPRINT"; then
  exit 0
fi

# Drift detected
METHOD=$(${PYTHON_BIN:-python3} -c "
import json
print(json.load(open('${CONTRACT}', encoding='utf-8')).get('method', 'unknown'))
" 2>/dev/null)

# Emit drift event (best effort)
"${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  "deploy.command_drift_blocked" \
  --payload "{\"attempted_cmd\":\"$(echo "$CMD" | head -c 200 | sed 's/"/\\"/g')\",\"expected_method\":\"${METHOD}\",\"fingerprint\":\"${FINGERPRINT}\"}" \
  >/dev/null 2>&1 || true

cat <<EOF
{"decision":"block","reason":"Deploy command drift detected. Project locked to method='${METHOD}' (fingerprint_pattern='${FINGERPRINT}'). Your command does not match: '${CMD:0:120}'. Use the locked method per .vg/DEPLOY-CONTRACT.json, OR explicitly change method via: /vg:override-resolve --deploy-method=<new_method> --reason='<why>' (logs override-debt)."}
EOF
exit 0
```

In `scripts/hooks/install-hooks.sh`, add PreToolUse Bash hook entry:

```bash
# Batch 20: PreToolUse Bash — deploy contract drift guard
{
  "matcher": "Bash",
  "hooks": [
    {"type": "command",
     "command": "python3 \"${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/vg-run-bash-hook.py\" \"${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/vg-deploy-contract-guard.sh\""
    }
  ]
}
```

(Adapt to install-hooks.sh's existing pattern — likely a JSON heredoc.)

```bash
git commit -m "feat(deploy): Batch 20 Task 2 — PreToolUse drift guard hook

scripts/hooks/vg-deploy-contract-guard.sh — PreToolUse hook on Bash.
Pattern-matches deploy-like commands (ansible, pm2, docker compose,
kubectl, helm, terraform, sudo systemctl, capistrano, fab). When match:
1. No DEPLOY-CONTRACT.json → BLOCK with bootstrap instruction.
2. Command does NOT match contract.fingerprint_pattern → BLOCK with
   override-resolve hint.
3. Match → allow.

Emits deploy.command_drift_blocked event on BLOCK for telemetry.

install-hooks.sh wires the hook globally.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Wire load-script into deploy steps + add /vg:deploy --init

**Files:**
- Modify: `commands/vg/_shared/test/deploy.md` STEP 5a_deploy — source load script + run from exported vars
- Modify: `commands/vg/_shared/deploy/execute.md` — same
- Modify: `commands/vg/_shared/deploy/preflight.md` — bootstrap check
- Modify: `commands/vg/deploy.md` frontmatter to support `--init` flag
- Mirrors
- Test: `tests/test_deploy_steps_source_load.py`

**Step 1: Failing test**

```python
"""tests/test_deploy_steps_source_load.py — Batch 20 deploy steps source loader."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]


def test_test_deploy_step_sources_loader():
    body = (REPO / "commands/vg/_shared/test/deploy.md").read_text(encoding="utf-8")
    assert "deploy-contract-load.py" in body, (
        "Batch 20: test/deploy.md STEP 5a_deploy must source deploy-contract-load.py "
        "to export DEPLOY_BUILD/DEPLOY_RESTART/DEPLOY_HEALTH from contract"
    )
    # The export must be USED — at least one $DEPLOY_BUILD / $DEPLOY_RESTART reference
    assert "$DEPLOY_BUILD" in body or "$DEPLOY_RESTART" in body or "$DEPLOY_HEALTH" in body, (
        "Batch 20: must reference exported $DEPLOY_* vars (not just source then ignore)"
    )


def test_deploy_execute_sources_loader():
    body = (REPO / "commands/vg/_shared/deploy/execute.md").read_text(encoding="utf-8")
    assert "deploy-contract-load.py" in body, (
        "Batch 20: deploy/execute.md must source deploy-contract-load.py"
    )


def test_deploy_preflight_bootstrap_check():
    body = (REPO / "commands/vg/_shared/deploy/preflight.md").read_text(encoding="utf-8")
    assert "DEPLOY-CONTRACT.json" in body, (
        "Batch 20: deploy/preflight.md must check for DEPLOY-CONTRACT.json "
        "and suggest --init if missing"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/_shared/test/deploy.md` STEP 5a_deploy, replace the comment-only block:

```bash
# Batch 20: source deploy contract — guarantees AI uses project's locked deploy method
LOAD_SCRIPT="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/deploy-contract-load.py"
[ -f "$LOAD_SCRIPT" ] || LOAD_SCRIPT="${REPO_ROOT:-.}/scripts/deploy-contract-load.py"
if [ ! -f "$LOAD_SCRIPT" ]; then
  echo "⛔ deploy-contract-load.py missing — required by Batch 20 hard gate" >&2
  exit 1
fi
eval "$(${PYTHON_BIN:-python3} "$LOAD_SCRIPT" --vg-dir "${PROJECT_VG_DIR:-.vg}" --env "${ENV:-sandbox}" 2>&1)" || {
  echo "⛔ deploy-contract-load failed — DEPLOY-CONTRACT.json missing or malformed" >&2
  echo "   Bootstrap: /vg:deploy --init  OR  python scripts/deploy-contract-init.py --method <X> ..." >&2
  exit 1
}

# 1. Record SHAs
LOCAL_SHA=$(git rev-parse --short HEAD)
[ -n "${RUN_PREFIX:-}" ] && PREV_SHA=$(run_on_target "git rev-parse --short HEAD") || PREV_SHA=$LOCAL_SHA

# 2. Pre-deploy (locally — e.g. git push)
[ -n "$DEPLOY_PRE" ] && eval "$DEPLOY_PRE"

# 3. Build + restart on target — uses contracted commands
run_on_target "$DEPLOY_BUILD && $DEPLOY_RESTART" || {
  echo "⛔ Build/restart failed via ${DEPLOY_METHOD}" >&2
  [ -n "$DEPLOY_ROLLBACK" ] && run_on_target "$DEPLOY_ROLLBACK"
  exit 1
}

# 4. Wait for startup
sleep 5

# 5. Health check
run_on_target "$DEPLOY_HEALTH" || {
  echo "⛔ Health failed via ${DEPLOY_METHOD}" >&2
  [ -n "$DEPLOY_ROLLBACK" ] && run_on_target "$DEPLOY_ROLLBACK"
  exit 1
}
echo "✓ Deploy (${DEPLOY_METHOD}) PASS on env=${ENV}"
```

Apply analogous bash to `commands/vg/_shared/deploy/execute.md` (it already partly reads env config — make it use loader).

In `commands/vg/_shared/deploy/preflight.md`, add early bootstrap check:

```bash
# Batch 20: ensure DEPLOY-CONTRACT.json exists before proceeding
CONTRACT_PATH="${PROJECT_VG_DIR:-.vg}/DEPLOY-CONTRACT.json"
if [ ! -f "$CONTRACT_PATH" ]; then
  if [[ "${ARGUMENTS:-}" =~ --init ]]; then
    echo "▸ /vg:deploy --init mode: bootstrapping DEPLOY-CONTRACT.json"
    echo "   AI controller must call AskUserQuestion to gather method + commands,"
    echo "   then run: python scripts/deploy-contract-init.py --method <X> --build '...' --restart '...' --health '...' --phase '${PHASE_NUMBER}' --run-id '${VG_RUN_ID}'"
    # AI handles via AskUserQuestion; on completion, contract should exist
  else
    echo "⛔ .vg/DEPLOY-CONTRACT.json missing — deploy locked-method contract required" >&2
    echo "   Bootstrap interactively: /vg:deploy --init" >&2
    echo "   OR explicit: python scripts/deploy-contract-init.py --method <ansible|pm2|docker|...> --build '...' --restart '...' --health '...'" >&2
    exit 1
  fi
fi
```

Update `commands/vg/deploy.md` argument-hint to include `--init`.

```bash
git commit -m "feat(deploy): Batch 20 Task 3 — wire deploy-contract-load into all deploy steps

test/deploy.md STEP 5a_deploy, deploy/execute.md, deploy/preflight.md
now source scripts/deploy-contract-load.py FIRST, then execute
\$DEPLOY_BUILD / \$DEPLOY_RESTART / \$DEPLOY_HEALTH via run_on_target.

Eliminates 'comment-only deploy' pattern (was: '# 1. Record SHAs / # 2.
Pre-deploy / # 3. Build + restart' as prose). AI no longer interprets
prose to invent commands — bash actually runs contract.

deploy/preflight.md blocks if DEPLOY-CONTRACT.json missing, suggests
/vg:deploy --init for interactive bootstrap.

deploy.md argument-hint adds --init flag.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: /vg:override-resolve --deploy-method extension

**Files:**
- Modify: `commands/vg/override-resolve.md` (add --deploy-method handling)
- Modify: `scripts/vg-override-resolve.py` if it exists (the actual implementation)
- Mirrors
- Test: `tests/test_override_resolve_deploy_method.py`

**Step 1: Failing test**

```python
"""tests/test_override_resolve_deploy_method.py — Batch 20 deploy method override."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
OR_MD = REPO / "commands" / "vg" / "override-resolve.md"


def test_override_resolve_documents_deploy_method():
    body = OR_MD.read_text(encoding="utf-8")
    assert "--deploy-method" in body, (
        "Batch 20: override-resolve.md must document --deploy-method flag "
        "for changing locked deploy contract method"
    )
    # Must mention contract file
    assert "DEPLOY-CONTRACT.json" in body, (
        "Batch 20: must reference the contract file the override modifies"
    )
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

In `commands/vg/override-resolve.md`, add documentation + dispatch for `--deploy-method`:

```markdown
## --deploy-method=<new_method> --reason="<text>"

Changes locked deploy method in `.vg/DEPLOY-CONTRACT.json`.

Use when project genuinely switches deploy infrastructure (e.g. migrate
ansible → kubectl). Logs override-debt entry. Re-runs deploy-contract-init
with --force.

```bash
if [[ "${ARGUMENTS}" =~ --deploy-method=([^ ]+) ]]; then
  NEW_METHOD="${BASH_REMATCH[1]}"
  REASON=$(echo "${ARGUMENTS}" | sed -nE 's/.*--reason="?([^"]+)"?.*/\1/p')
  if [ -z "$REASON" ]; then
    echo "⛔ --deploy-method requires --reason='<why>'" >&2
    exit 1
  fi
  echo "▸ Changing locked deploy method to: ${NEW_METHOD}"
  echo "   AI controller: gather new build/restart/health commands via AskUserQuestion,"
  echo "   then run: python scripts/deploy-contract-init.py --method ${NEW_METHOD} --build '...' --restart '...' --health '...' --force --phase ${PHASE_NUMBER:-?} --run-id ${VG_RUN_ID:-?}"
  "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event "deploy.contract_override" \
    --payload "{\"new_method\":\"${NEW_METHOD}\",\"reason\":\"${REASON//\"/\\\"}\"}" || true
  type -t log_override_debt >/dev/null 2>&1 && \
    log_override_debt "deploy-method-change" "${PHASE_NUMBER:-global}" "${NEW_METHOD}: ${REASON}" "${PHASE_DIR:-.}"
fi
```

```bash
git commit -m "feat(deploy): Batch 20 Task 4 — /vg:override-resolve --deploy-method extension

Adds --deploy-method=<X> --reason='<text>' to override-resolve. Allows
project to legitimately migrate deploy infra (ansible → kubectl, etc).
Emits deploy.contract_override event + logs override-debt. AI controller
then re-runs deploy-contract-init --force with new commands.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Release v4.22.0

Bump VERSION 4.21.0 → 4.22.0. CHANGELOG entry. Tag v4.22.0. Push. Re-sync ~/.vgflow. Check codex mirror; regen if drift.

End of Batch 20 plan. Estimated 4 hours.
