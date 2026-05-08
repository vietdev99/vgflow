# VG Global Install + Layout Refactor — Design

**Date:** 2026-05-09
**Author:** Claude (brainstorming session) + caveman-investigator (architecture inventory)
**Target version:** v3.0.0 (major, breaking)
**Status:** APPROVED — proceed to writing-plans

## Goal

Move VG harness core (skills, commands, scripts, hooks) to a **global install location** (`~/.vgflow/` — single-version), keep only DYNAMIC project state in `.vg/`. Decouple deploy from phase scope. Ship `vgflow` as a public npm package.

## Architecture summary

Static harness assets ship globally; project repos contain only ephemeral state + tracked phase artifacts under `.vg/`. Path resolver walks `cwd → .git` (with `__file__` fallback for legacy installs) so global scripts find project state correctly. Hook scripts placed in `~/.claude/settings.json` (global Claude config) point at `~/.vgflow/scripts/hooks/...`. First-run `/vg:install` ASKs global vs project mode, marker `.vg/.install-target` records choice silently after.

## Tech stack

- **Distribution:** npm public package `vgflow` + standalone `install.sh` (curl-pipe-bash)
- **CLI entry:** `bin/vg.js` (Node) → `bin/vg-cli-dispatcher.sh` (Bash)
- **Static layout:** `~/.vgflow/{commands,skills,scripts,schemas,templates,codex-skills,bin}`
- **Dynamic state:** project's `.vg/` directory (existing)
- **Hooks:** Bash scripts under `~/.vgflow/scripts/hooks/`, registered via `~/.claude/settings.json`
- **Resolver:** Python `_repo_root.py` priority cwd > `__file__` > `VG_REPO_ROOT` env

---

## 1. Architecture

### 1.1 Layout

```
GLOBAL (single root, no version subdirs):
~/.vgflow/
  ├── bin/{vg.js, vg-cli-dispatcher.sh}
  ├── commands/vg/                    # 277 .md files (55 + 222 _shared)
  ├── skills/                         # 17 skills (vg-* + utility)
  ├── scripts/                        # 171 .py + .sh
  │   ├── hooks/                      # 13 hook scripts
  │   ├── codex-hooks/                # 6 Codex hooks
  │   ├── vg-orchestrator/            # core orchestrator
  │   ├── validators/                 # schema validators
  │   ├── bootstrap-loader.py         # rule injector (meta-memory)
  │   ├── bootstrap-shadow-evaluator.py
  │   ├── bootstrap-consolidate.py    # NEW per meta-memory plan (Dreams 4-phase)
  │   └── bootstrap-attribute-outcome.py # NEW per meta-memory plan
  ├── schemas/                        # 21 .json
  ├── templates/                      # vg + codex templates
  ├── codex-skills/                   # 74 codex skill mirrors
  ├── codex-agents/                   # 3 codex agents
  ├── VERSION                         # installed version
  └── .installed                      # install marker (version, source, date)

~/.claude/settings.json               # global Claude hooks → ~/.vgflow/...
~/.codex/{config.toml, hooks.json}    # global Codex config → ~/.vgflow/...

PROJECT (lightweight per-project):
project-root/
  ├── README.md, CHANGELOG.md, LICENSE
  ├── (project code: src/, tests/, package.json...)
  └── .vg/
      │
      │ ── TRACKED (via .gitignore whitelist) ──
      ├── ROADMAP.md                  # was: project-root/ROADMAP.md
      ├── FOUNDATION.md               # was: project-root/FOUNDATION.md
      ├── config.md                   # was: project-root/vg.config.md
      ├── OVERRIDE-DEBT.md
      ├── .install-target             # marker: "global" or "project"
      ├── phases/{N}/                 # phase artifacts
      ├── bootstrap/{ACCEPTED,REJECTED,RETRACTED}.md
      ├── bootstrap/rules/{slug}.md
      ├── bootstrap/overlay.yml
      ├── bootstrap/CONSOLIDATION-LOG.md  # Dreams audit append-only
      ├── bootstrap/MEMORY.md             # ≤200-line index (Anthropic pattern)
      ├── bootstrap/topics/{topic}.md     # demoted from MEMORY.md
      ├── deploy/STATE.json               # project-level deploy state (Section 10)
      ├── deploy/history.jsonl            # append-only deploy events
      │
      │ ── UNTRACKED (default ignored) ──
      ├── events.db
      ├── events.jsonl
      ├── active-runs/{sid}.json
      ├── runs/{run_id}/
      ├── .session-context.json
      ├── bootstrap/CANDIDATES.md
      ├── bootstrap/state.json            # Dreams gate timestamps
      ├── bootstrap/.consolidation.lock
      ├── deploy/deploy-log.{env}.txt
      ├── deploy/.deploy.lock
      └── .backup-{date}/                 # auto-backup khi switch mode
```

### 1.2 `.gitignore` whitelist semantics

```gitignore
.vg/*

!.vg/ROADMAP.md
!.vg/FOUNDATION.md
!.vg/config.md
!.vg/OVERRIDE-DEBT.md
!.vg/.install-target
!.vg/phases/
!.vg/phases/**/*.md
!.vg/phases/**/*.json
!.vg/bootstrap/
!.vg/bootstrap/{ACCEPTED,REJECTED,RETRACTED,CONSOLIDATION-LOG,MEMORY}.md
!.vg/bootstrap/rules/
!.vg/bootstrap/rules/*.md
!.vg/bootstrap/overlay.yml
!.vg/bootstrap/topics/
!.vg/bootstrap/topics/*.md
!.vg/deploy/
!.vg/deploy/STATE.json
!.vg/deploy/history.jsonl

# Re-ignore subpaths
.vg/phases/**/.runtime-state.json
.vg/bootstrap/CANDIDATES.md
.vg/bootstrap/state.json
.vg/bootstrap/.consolidation.lock
.vg/deploy/deploy-log.*
.vg/deploy/.deploy.lock
```

---

## 2. Path resolution refactor

### 2.1 Three roots

| Symbol | Where | Resolution |
|---|---|---|
| `VG_HOME` | global install dir | `~/.vgflow/` (set by installer) |
| `VG_PROJECT` | current project root | walk `cwd → .git` |
| `VG_STATE` | `.vg/` directory | `${VG_PROJECT}/.vg/` |

### 2.2 `_repo_root.py` revised priority

```python
def find_repo_root(start_file=None):
    # 1. Explicit env
    env = os.environ.get("VG_REPO_ROOT") or os.environ.get("VG_PROJECT")
    if env:
        return Path(env).resolve()

    # 2. Walk from cwd (NEW — works for global install)
    cwd = Path.cwd()
    for c in [cwd, *cwd.parents]:
        if (c / ".git").exists():
            return c

    # 3. Walk from __file__ anchor (legacy fallback)
    if start_file:
        anchor = Path(start_file).resolve().parent
        for c in [anchor, *anchor.parents]:
            if (c / ".git").exists():
                return c

    print("WARN: ...", file=sys.stderr)
    return Path.cwd().resolve()
```

**Key change:** swap priority 2 ↔ 3. Cwd-walk first → works global + legacy. `__file__`-walk fallback compat.

### 2.3 New helper `find_vg_home()`

```python
def find_vg_home():
    # 1. Explicit env
    env = os.environ.get("VG_HOME")
    if env:
        return Path(env).resolve()

    # 2. Marker-driven
    project = find_repo_root()
    marker = project / ".vg" / ".install-target"
    if marker.exists():
        target = marker.read_text().strip()
        if target == "global":
            home = Path.home() / ".vgflow"
            if home.exists():
                return home
            raise RuntimeError("Marker=global but ~/.vgflow/ missing. Run /vg:install --repair.")
        elif target == "project":
            return project / ".claude"

    # 3. Legacy detect
    if (project / ".claude" / "VGFLOW-VERSION").exists():
        return project / ".claude"

    # 4. Global fallback
    home = Path.home() / ".vgflow"
    if home.exists():
        return home
    raise RuntimeError("VG not installed. Run: npm install -g vgflow")
```

### 2.4 Touch sites (~5 critical)

- `_repo_root.py` (canonical + .claude mirror) — swap priority + add `VG_PROJECT` alias
- `scripts/hooks/_lib.sh` — new `vg_resolve_project_root()` shell helper
- `scripts/hooks/vg-pre-tool-use-bash.sh` — use cwd-resolved `.vg/` paths (no change needed if cwd correct)
- `scripts/backfill-registry.py:36` — replace `parents[2]` walk with `find_repo_root()`
- All bootstrap loader/validator scripts — verify use `find_repo_root()`

---

## 3. Install + upgrade flow

### 3.1 First-run `/vg:install`

1. Detect existing markers (`.vg/.install-target`, `~/.vgflow/.installed`)
2. Detect existing project legacy files (`.claude/commands/vg/`, etc.)
3. ASK user: global vs project (Recommended: global)
4. **GLOBAL chosen:**
   - Verify `~/.vgflow/` exists (else install via npm)
   - Backup project legacy: `cp -r .claude/{commands/vg,skills/vg-*,scripts} .vg/.backup-{date}/`
   - Remove project legacy
   - Write `~/.claude/settings.json` hooks → `~/.vgflow/scripts/hooks/...`
   - `echo "global" > .vg/.install-target`
   - Commit
5. **PROJECT chosen:**
   - Run existing `/vg:sync` (project-local mirror)
   - Write `.claude/settings.json` → `${CLAUDE_PROJECT_DIR}`
   - `echo "project" > .vg/.install-target`

### 3.2 Subsequent runs (silent)

```
/vg:install (re-run)
  └─ read .vg/.install-target → "global"|"project"
     └─ silent install/update theo target chosen
```

### 3.3 Update + switch

- `/vg:update` — `git pull ~/.vgflow/` (global) or `/vg:sync` (project)
- `/vg:install --target=global` — switch project → global (with backup)
- `/vg:install --target=project` — switch global → project

### 3.4 Recovery (no custom rollback script)

Native methods cover all rollback scenarios:
1. **Pin npm version cũ:** `npm install -g vgflow@<old>`
2. **Restore project state:** `cp -r .vg/.backup-{date}/* .`
3. **Git history:** `git revert <migration-sha>` or `git reset --hard <pre-migration>`

---

## 4. Hook strategy

### 4.1 Global settings.json (Recommended)

Hooks declared at `~/.claude/settings.json` (global Claude config). Apply EVERY project user opens — install once.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "bash \"$HOME/.vgflow/scripts/hooks/vg-user-prompt-submit.sh\""}]}
    ]
  }
}
```

VG context guard pattern (existing) silent-exits when `.vg/active-runs/` missing → no harm in non-VG projects.

### 4.2 Per-project settings.json (legacy fallback)

Project mode: hooks in project's `.claude/settings.json`, command paths still point global (`$HOME/.vgflow/...`).

### 4.3 Hook script invariants

Hooks fire with `cwd = project root` (Claude Code spawns hook with cwd = project). `.vg/` resolution via cwd. Existing scripts work as-is — only LOCATION changes.

### 4.4 install-hooks.sh `--mode` flag

```bash
bash install-hooks.sh --target ~/.claude/settings.json --mode global
bash install-hooks.sh --target ./.claude/settings.json --mode project

# _cmd() output:
mode=global  → "bash \"$HOME/.vgflow/scripts/hooks/X.sh\""
mode=project → "bash \"${CLAUDE_PROJECT_DIR}/.claude/scripts/hooks/X.sh\""
```

---

## 5. Migration path existing projects

### 5.1 `vg-migrate-v3.sh` flow

```
1. Detect current state (legacy files present, VG version, .vg/ exists)
2. ASK target (global / project / skip)
3. Backup → .vg/.backup-{date}/
4. Move root docs → .vg/:
     git mv ROADMAP.md       .vg/ROADMAP.md
     git mv FOUNDATION.md    .vg/FOUNDATION.md
     git mv vg.config.md     .vg/config.md
5. Branch by target:
   GLOBAL:
     rm -rf .claude/{commands/vg,skills/vg-*,scripts,schemas,templates/vg}
     rm -rf .codex/{skills/vg-*,agents}
     bash ~/.vgflow/scripts/hooks/install-hooks.sh --target ~/.claude/settings.json --mode global
     echo "global" > .vg/.install-target
   PROJECT:
     /vg:sync (existing)
     bash scripts/hooks/install-hooks.sh --target .claude/settings.json --mode project
     echo "project" > .vg/.install-target
6. Update .gitignore whitelist
7. Update path references in .vg/ROADMAP.md, .vg/FOUNDATION.md
8. Smoke test (/vg:doctor, /vg:health)
9. Commit
```

### 5.2 Backwards compat (1 minor cycle)

- v3.0.0: dual-mode resolver, prefer new layout, fallback legacy
- v3.1.0: legacy mode emit DEPRECATED warning
- v4.0.0: drop legacy

---

## 6. Distribution + sync flow

### 6.1 Install methods

1. **Recommended — npm public:**
   ```bash
   npm install -g vgflow
   vg install --global    # wires hooks
   ```

2. **One-line installer:**
   ```bash
   curl -fsSL https://raw.githubusercontent.com/vietdev99/vgflow/main/install.sh | bash
   ```

3. **Manual git clone:**
   ```bash
   git clone https://github.com/vietdev99/vgflow.git ~/.vgflow
   cd ~/.vgflow && bash install.sh
   ```

4. **Project-local (legacy compat):** existing `/vg:sync` flow

### 6.2 `/vg:sync` redesign

```
/vg:sync
  ├─ Read .vg/.install-target
  ├─ "global": cd ~/.vgflow, git pull, update VERSION
  └─ "project": existing flow (project-local mirror)
```

### 6.3 npm package skeleton (DONE — `173f598`)

- `package.json` — name=vgflow, bin=vg, license=MIT
- `bin/vg.js` — Node entry, spawn bash dispatcher with VG_HOME env
- `bin/vg-cli-dispatcher.sh` — bash router (version, help, install, sync, doctor, health)
- `scripts/npm-postinstall.js` — conservative print + prompt (no auto-modify settings)
- `scripts/npm-prepublish-check.js` — gate VERSION ≠ package.json
- `.npmignore` — exclude .git/, .vg/, .claude/, tests/, dev-phases/
- `docs/PUBLISH-NPM.md` — full publish workflow

---

## 7. Backwards compat + rollout

### 7.1 Resolver dual-mode

```
Hook fires (project cwd)
        ↓
   resolve_vg_home()
        ↓
   marker?
   ├─ "global"  → ~/.vgflow/
   ├─ "project" → .claude/
   └─ no marker → ~/.vgflow/ if exists, else .claude/ (legacy)
```

### 7.2 Recovery (no custom script)

1. `npm install -g vgflow@<old>` (downgrade)
2. `cp -r .vg/.backup-{date}/* .` (restore)
3. `git revert <migration-sha>` or `git reset --hard <pre-migration>`

### 7.3 Multi-version global install (defer v3.x)

```
~/.vgflow/
  ├── current → versions/2.53.0/
  └── versions/{2.52.2,2.53.0,3.0.0}/
```

Project pin via `.vg/config.md` field `vg_version_pin`. v3.0.0 NO pin support (single version). v3.1+ adds.

---

## 8. Risks + edge cases

### 8.1 Cross-platform

| Risk | Mitigation |
|---|---|
| Windows symlink requires admin | v3.0 single-version (no symlink). Multi-version v3.x defer |
| Git Bash vs WSL bash | `bin/vg.js findBash()` prefers Git Bash; VG_BASH override |
| Path with spaces | All scripts quote `"${VG_HOME}"` |
| macOS SIP restrictions | Doc fallback `/usr/local/lib/vgflow/` |

### 8.2 Hook execution

| Risk | Mitigation |
|---|---|
| Hook fires in non-VG project | VG context guard exit 0 (existing pattern) |
| `~/.claude/settings.json` corrupted | Backup before write, validate JSON, rollback on error |
| `${CLAUDE_PROJECT_DIR}` unset | Fallback `${CLAUDE_PROJECT_DIR:-$(pwd)}` |

### 8.3 Concurrent install/upgrade

| Risk | Mitigation |
|---|---|
| 2 sessions `/vg:install` race | flock `~/.vgflow/.install.lock` |
| Update mid-VG-run | v2.52.2 cross-session destructive guard blocks (already ships) |

### 8.4 Migration corruption

| Risk | Mitigation |
|---|---|
| Migration crash mid-flow | Idempotent + status marker `.vg/.migration-status` |
| `.gitignore` whitelist wrong | `vg-migrate-verify.sh` post-migrate validator |
| External CI references root docs | Migration warns + suggests update |

### 8.5 Version skew

| Risk | Mitigation |
|---|---|
| Project pin vs global mismatch | v3.0 no pin. User wanting pin → keep project mode. v3.x add pin. |
| Multi-machine version drift | Pin in CI `package.json` devDeps |

### 8.6 CI/CD

| Risk | Mitigation |
|---|---|
| `~/.claude/settings.json` missing in CI | `vg install` skip claude write, install only project |
| Cache `~/.vgflow/` stale | Cache key by `vgflow` version |

---

## 9. Meta-memory cross-cut + sequencing

### 9.1 Static vs dynamic split

| Component | Where |
|---|---|
| Reflector skill | `~/.vgflow/skills/vg-reflector/` (global) |
| Bootstrap loader | `~/.vgflow/scripts/bootstrap-loader.py` (global) |
| Shadow evaluator | `~/.vgflow/scripts/bootstrap-shadow-evaluator.py` (global) |
| Consolidation engine | `~/.vgflow/scripts/bootstrap-consolidate.py` (global, NEW) |
| Attribution prober | `~/.vgflow/scripts/bootstrap-attribute-outcome.py` (global, NEW) |
| Reflector triggers | `~/.vgflow/commands/vg/{deploy,test,accept,roam,amend}.md` (global) |
| Inject sites | `~/.vgflow/commands/vg/_shared/{build,accept}/preflight.md` (global) |
| Rules + audit | `project/.vg/bootstrap/{ACCEPTED.md, rules/*.md, overlay.yml}` (per-project tracked) |
| Candidates draft | `project/.vg/bootstrap/CANDIDATES.md` (per-project untracked) |
| Dreams gate state | `project/.vg/bootstrap/state.json` (per-project untracked) |

### 9.2 Cross-cut invariants

1. Static scripts read DYNAMIC project state via cwd (resolver Section 2)
2. Reflector NEVER reads AI transcript (echo-chamber guard)
3. Causal attribution mandatory (procedural rules + sequence checksum + per-step probe)
4. Cross-session lock cover bootstrap consolidation (`.consolidation.lock` per-project, v2.52.2 cross-session destructive guard)

### 9.3 Sequencing roadmap (Option A — meta-memory first)

```
v2.52.2 (today) ──→ v2.53.0 ──→ v2.54-v2.59 ──→ v3.0.0
   shipped         npm pkg      META-MEMORY     GLOBAL INSTALL
                   skeleton    (23 tasks)       + DEPLOY DECOUPLE
                   (DONE)
```

**Rationale:**
- Meta-memory implementation touches existing canonical files (commands/, scripts/, skills/) under v2.x project-local layout
- Smaller blast radius — incremental v2.5x patches/minors
- Validates causal attribution + Dreams pattern in production before bundling to major v3
- v3.0.0 = pure layout refactor (no new behavior)

### 9.4 Meta-memory phase mapping → version

| Stage | Tasks | Target version |
|---|---|---|
| 0 — Pre-flight | 1 | v2.53.0 |
| 1 — Schema v1.1 + validator | 2 | v2.53.0 |
| 2 — 5 reflector triggers | 5 | v2.54.0 - v2.55.0 |
| 3 — Causal attribution (HARD GATE) | 3 | v2.56.0 |
| 4 — 4 inject sites | 4 | v2.57.0 |
| 5 — Dreams 4-phase consolidation | 6 | v2.58.0 - v2.59.0 |
| 6 — Rollout flag + E2E | 5 | v2.59.x stabilize |

3-month estimate.

### 9.5 v3.0.0 cumulative scope (NO meta-memory features)

1. Layout refactor — root docs → `.vg/`
2. Path resolver dual-mode (global vs project)
3. npm global install via `vg install --global`
4. Hook installer dual-mode
5. **Deploy decouple — project-level state, no phase scope** (Section 10)
6. Consumer migrations for deploy state references
7. Telemetry event rename (`phase.deploy_*` → `deploy.*`) with backwards-compat aliases
8. Migration script `vg-migrate-v3.sh`

---

## 10. Deploy decouple (bundle v3.0)

### 10.1 Architecture change

```
BEFORE (v2.x):
  /vg:deploy 5 --envs=fly.io
       ↓
  reads .vg/phases/5/CONTEXT.md
       ↓
  writes .vg/phases/5/DEPLOY-STATE.json
       ↓
  emits phase.deploy_completed (phase=5)

AFTER (v3.0):
  /vg:deploy --envs=fly.io
       ↓
  detects phase context from .vg/active-runs/*.json (auto)
       ↓
  writes .vg/deploy/STATE.json (project-level)
       ↓
  appends .vg/deploy/history.jsonl
       ↓
  emits deploy.completed (phase_context derived, audit only)
```

### 10.2 New layout `.vg/deploy/`

```
.vg/deploy/
  ├── STATE.json
  │   {
  │     "schema_version": 1,
  │     "envs": {
  │       "fly.io": {
  │         "sha": "abc",
  │         "deployed_at": "...",
  │         "phase_context": "5",
  │         "previous_sha": "def",
  │         "rollback_target": "def",
  │         "health": "passing",
  │         "deploy_duration_sec": 42,
  │         "deploy_commands": [...]
  │       }
  │     },
  │     "preferred_env_for_phase": {"5": "fly.io"},
  │     "active_environments": ["fly.io", "staging", "prod"]
  │   }
  ├── history.jsonl                    # append-only event log
  ├── deploy-log.{env}.txt             # per-env stdout
  └── deploy-log.{env}.archive/        # rotated logs
```

### 10.3 Skill arg signature change

```
v2.x: /vg:deploy <phase> [--envs=...] [--prod-confirm-token=DEPLOY-PROD-{phase}]
v3.0: /vg:deploy [--envs=...] [--phase=<N>] [--prod-confirm-token=DEPLOY-PROD-{sha-prefix}]
```

- Phase arg: optional override
- Prod confirm token: SHA-based, not phase-based (matches reality: deploy = code at SHA)

### 10.4 Telemetry rename

| Old | New | Migration |
|---|---|---|
| `phase.deploy_started` | `deploy.started` | Both emit 1 minor cycle |
| `phase.deploy_completed` | `deploy.completed` | Same |
| `phase.deploy_failed` | `deploy.failed` | Same |

### 10.5 Migration script

```bash
# vg-migrate-deploy-v3.sh (subset of vg-migrate-v3.sh)

# Collect per-phase DEPLOY-STATE.json
for f in .vg/phases/*/DEPLOY-STATE.json; do
  jq . "$f" >> .vg/.tmp/deploy-states-collected.jsonl
done

# Merge: latest SHA per env wins
python3 .vg/.scripts/merge-deploy-states.py \
  --input .vg/.tmp/deploy-states-collected.jsonl \
  --output .vg/deploy/STATE.json

# Backup originals
mv .vg/phases/*/DEPLOY-STATE.json .vg/.backup-{date}/phases-deploy-state/

# Generate history.jsonl from events.db
python3 .vg/.scripts/build-deploy-history.py \
  --events .vg/events.db \
  --output .vg/deploy/history.jsonl
```

### 10.6 Consumer updates (~10 touch sites)

| Consumer | Was | Now |
|---|---|---|
| `vg:scope` step 1b `preferred_env_for` | `.vg/phases/{N}/DEPLOY-STATE.json` | `.vg/deploy/STATE.json.preferred_env_for_phase[{N}]` |
| Build pre-test gate | Per-phase | Project-level |
| Test runtime env detection | Per-phase | Project-level |
| `enrich-env-question.py` | Per-phase | Project-level |
| Reflector post-deploy (Section 9) | `phase.deploy_completed` + per-phase state | `deploy.completed` + project-level state |

### 10.7 Risks specific

| Risk | Mitigation |
|---|---|
| 2 sessions deploy same env race | flock `.vg/deploy/.deploy.lock` per-env + v2.52.2 destructive guard |
| Auto-detected phase context wrong | `--phase=<N>` override + warn if mismatch |
| `history.jsonl` grows unbounded | Rotate at 10MB → `.vg/deploy/history-{date}.jsonl.gz` |
| Per-phase state.json orphaned | Migration backup, never auto-delete |
| Rollback ambiguity per-phase | `history.jsonl` `phase_context` field = audit. Rollback = `previous_sha` from STATE.json |

---

## References

- Meta-memory design: `docs/plans/2026-05-08-meta-memory-design.md`
- Meta-memory implementation plan: `docs/plans/2026-05-08-meta-memory-implementation.md`
- npm publish workflow: `docs/PUBLISH-NPM.md`
- Multi-session guide: `docs/multi-session.md`
- Investigator findings (this brainstorm): inline in conversation history
- Existing infra:
  - `.claude/scripts/vg-orchestrator/_repo_root.py` — resolver
  - `.claude/scripts/hooks/install-hooks.sh` — hook installer (POSIX bypass v2.51.14)
  - `.claude/scripts/hooks/vg-pre-tool-use-bash.sh` — destructive guard (v2.52.2 cross-session)
  - `commands/vg/deploy.md` — current per-phase deploy

## Open questions for verification round

- npm publish access verified before v3.0 ships? (`vgflow` name available, registered)
- Plugin marketplace timing — defer to v3.x (after layout stable ≥3 months)
- Multi-version global install demand — wait for user request or pre-design v3.1?
- vg.config.md secrets handling — convention `.env` (gitignored), `.vg/config.md` only public env names

## Implementation handoff

Next step: invoke `superpowers:writing-plans` to convert this design into a bite-sized TDD implementation plan. Plan will cover v2.53.0 (npm skeleton release) + v2.54-2.59 (meta-memory phases per Section 9.4) + v3.0.0 (this design's full scope).
