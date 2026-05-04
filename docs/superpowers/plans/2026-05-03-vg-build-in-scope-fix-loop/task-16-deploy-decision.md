<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Codex Round 2 Correction B inlined below the original task body. -->

## Task 16: Deploy decision gate + ENV-BASELINE policy reader

**Files:**
- Create: `scripts/lib/deploy_decision.py`
- Test: `tests/test_deploy_decision.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_deploy_decision.py`:

```python
"""Deploy decision policy — reads ENV-BASELINE.md and proposes target env."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_web_fullstack_default_proposes_sandbox(tmp_path: Path) -> None:
    eb = tmp_path / "ENV-BASELINE.md"
    eb.write_text(textwrap.dedent("""
        # Environment Baseline — X

        **Profile:** web-fullstack

        ## Recommended tech stack
        | Layer | Tool | Version | Rationale |
        |---|---|---|---|
        | Runtime | Node | 22 | LTS |

        ## Environment matrix
        | Env | Purpose | Hosting | Run command | Deploy method | DB strategy | Secrets source | Auto-promote? |
        |---|---|---|---|---|---|---|---|
        | dev | local | localhost | dev | none | sqlite | env | – |
        | sandbox | AI test | vps | pm2 | rsync | postgres | vault | from /vg:test |
        | staging | UAT | staging | (cdn) | git push | postgres | vercel | manual |
        | prod | prod | app.com | (cdn) | git push | postgres | vercel | approval |

        ## Decisions (E-XX namespace)
        ### E-01: x
        **Reasoning:** y
        **Reverse cost:** LOW
        **Sources cited:** https://x
    """).strip(), encoding="utf-8")

    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from deploy_decision import propose_target  # type: ignore

    proposal = propose_target(eb, phase_changes={"frontend": True, "backend": True})
    assert proposal["recommended_env"] == "sandbox"
    assert "sandbox" in proposal["available_envs"]
    assert proposal["confidence"] >= 0.7
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_frontend_only_phase_proposes_staging(tmp_path: Path) -> None:
    eb = tmp_path / "ENV-BASELINE.md"
    eb.write_text(textwrap.dedent("""
        # Environment Baseline — X

        **Profile:** web-frontend-only

        ## Recommended tech stack
        | Layer | Tool | Version | Rationale |
        |---|---|---|---|
        | Runtime | Node | 22 | x |

        ## Environment matrix
        | Env | Purpose | Hosting | Run command | Deploy method | API target | Secrets source | Auto-promote? |
        |---|---|---|---|---|---|---|---|
        | dev | local | localhost | dev | none | mock | env | – |
        | staging | UAT | staging | (cdn) | git push | prod-api | vercel | manual |
        | prod | prod | app | (cdn) | git push | prod | vercel | approval |

        ## Decisions (E-XX namespace)
        ### E-01: x
        **Reasoning:** y
        **Reverse cost:** LOW
        **Sources cited:** https://x
    """).strip(), encoding="utf-8")

    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from deploy_decision import propose_target  # type: ignore

    proposal = propose_target(eb, phase_changes={"frontend": True, "backend": False})
    # frontend-only profile lacks sandbox; staging is the next best for FE smoke
    assert proposal["recommended_env"] == "staging"
    sys.path.remove(str(REPO / "scripts" / "lib"))


def test_missing_envbaseline_returns_skip(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    from deploy_decision import propose_target  # type: ignore

    proposal = propose_target(tmp_path / "absent.md", phase_changes={})
    assert proposal["recommended_env"] == "skip"
    assert "missing" in proposal["reason"].lower()
    sys.path.remove(str(REPO / "scripts" / "lib"))
```

- [ ] **Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_deploy_decision.py -v`
Expected: 3 failures.

- [ ] **Step 3: Write the policy reader**

Create `scripts/lib/deploy_decision.py`:

```python
"""deploy_decision — policy layer reading ENV-BASELINE.md.

Per-profile default policy:
  web-fullstack | web-backend-only → recommend sandbox
  web-frontend-only                → recommend staging (no sandbox)
  mobile                           → recommend internal-test
  cli-tool | library               → recommend skip (no deploy needed)

Phase-changes hint optional: {"frontend": bool, "backend": bool, "schema": bool}.
If schema changed, recommend staging (need real DB).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

PROFILE_RE = re.compile(r"\*\*Profile:\*\*\s*(\S+)")
ENV_ROW_RE = re.compile(r"^\|\s*([a-z][a-z0-9-]*)\s*\|", re.MULTILINE)


def _parse_env_baseline(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    profile_match = PROFILE_RE.search(text)
    profile = profile_match.group(1) if profile_match else "unknown"

    # Extract env names from the Environment matrix table data rows
    matrix_section = re.search(r"##\s+Environment matrix(.+?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    envs: list[str] = []
    if matrix_section:
        for m in ENV_ROW_RE.finditer(matrix_section.group(1)):
            name = m.group(1).strip()
            if name not in {"env", "---"} and name not in envs:
                envs.append(name)
    return {"profile": profile, "envs": envs}


_PROFILE_DEFAULT_ENV = {
    "web-fullstack": "sandbox",
    "web-backend-only": "sandbox",
    "web-frontend-only": "staging",
    "mobile": "internal-test",
    "mobile-native": "internal-test",
    "mobile-cross": "internal-test",
    "cli-tool": "skip",
    "library": "skip",
}


def propose_target(env_baseline_path: Path, phase_changes: dict[str, bool] | None = None) -> dict[str, Any]:
    """Return {recommended_env, available_envs, profile, reason, confidence}."""
    if not env_baseline_path.exists():
        return {
            "recommended_env": "skip",
            "available_envs": [],
            "profile": "unknown",
            "reason": "ENV-BASELINE.md missing — run /vg:project --update --env-baseline",
            "confidence": 0.0,
        }

    parsed = _parse_env_baseline(env_baseline_path)
    profile = parsed["profile"]
    envs = parsed["envs"]
    default_env = _PROFILE_DEFAULT_ENV.get(profile, "skip")

    # Phase-changes hint: schema change → bump to staging (real DB)
    if phase_changes and phase_changes.get("schema") and "staging" in envs:
        return {
            "recommended_env": "staging",
            "available_envs": envs,
            "profile": profile,
            "reason": "schema change requires real DB — staging recommended",
            "confidence": 0.85,
        }

    # If default env not in available envs, fallback
    if default_env != "skip" and default_env not in envs:
        # Pick first available non-dev/non-prod env
        candidates = [e for e in envs if e not in {"dev", "prod"}]
        if candidates:
            return {
                "recommended_env": candidates[0],
                "available_envs": envs,
                "profile": profile,
                "reason": f"profile default {default_env!r} unavailable — using {candidates[0]!r}",
                "confidence": 0.6,
            }

    return {
        "recommended_env": default_env,
        "available_envs": envs,
        "profile": profile,
        "reason": f"profile {profile!r} default policy",
        "confidence": 0.8 if default_env in envs else 0.4,
    }
```

- [ ] **Step 4: Run tests + commit**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_deploy_decision.py -v
git add scripts/lib/deploy_decision.py tests/test_deploy_decision.py
git commit -m "feat(pre-test): add deploy decision policy reading ENV-BASELINE.md"
```
Expected: 3 passed.



---

## Codex Round 2 Correction B (mandatory — apply on top of the original task body above)

### Correction B — Task 16: deterministic schema detection

**Problem (Codex #3):** `phase_changes={"schema":bool}` was a stub. Need
deterministic detection (not LLM keyword grep on PLAN).

**Patch — Add to `scripts/lib/deploy_decision.py`:**

```python
def detect_phase_changes(phase_dir: Path, repo_root: Path = Path(".")) -> dict[str, bool]:
    """Detect what kinds of changes the phase introduced. Deterministic file evidence.

    Order of authority (Codex round 2):
      1. Task capsules: `${PHASE_DIR}/.task-capsules/task-NN.capsule.json` `edits_files`
      2. Build progress: `${PHASE_DIR}/.build-progress.json` `tasks[].files_touched`
      3. git diff: `git diff --name-only <prev-phase-tag>..HEAD` (if previous tag exists)
      4. PLAN keyword grep — fallback only
    """
    flags = {"frontend": False, "backend": False, "schema": False}

    paths_touched: set[str] = set()

    # 1. Task capsules
    capsule_dir = phase_dir / ".task-capsules"
    if capsule_dir.exists():
        import json as _json
        for cap in capsule_dir.glob("task-*.capsule.json"):
            try:
                data = _json.loads(cap.read_text(encoding="utf-8"))
                for f in data.get("edits_files", []) + [data.get("edits_endpoint", "")]:
                    if f:
                        paths_touched.add(f)
            except (OSError, ValueError):
                continue

    # 2. Build progress
    progress = phase_dir / ".build-progress.json"
    if progress.exists() and not paths_touched:
        try:
            import json as _json
            data = _json.loads(progress.read_text(encoding="utf-8"))
            for t in data.get("tasks", []):
                paths_touched.update(t.get("files_touched", []))
        except (OSError, ValueError):
            pass

    # 3. git diff (defensive — only if previous-phase tag exists)
    if not paths_touched:
        try:
            import subprocess as _sp
            r = _sp.run(["git", "diff", "--name-only", "HEAD~1..HEAD"],
                       cwd=repo_root, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                paths_touched.update(p for p in r.stdout.splitlines() if p.strip())
        except (FileNotFoundError, _sp.TimeoutExpired):
            pass

    # Classify
    for p in paths_touched:
        pl = p.lower()
        if any(x in pl for x in ("apps/web/", "apps/frontend/", "src/components/", ".tsx", ".jsx", "/pages/", "/views/")):
            flags["frontend"] = True
        if any(x in pl for x in ("apps/api/", "apps/backend/", "src/server/", "/handlers/", "/routes/", "/controllers/")):
            flags["backend"] = True
        if any(x in pl for x in ("/migrations/", "/schema.sql", "schema.prisma", "models.py", "/db/schema/", ".sql", "alembic/")):
            flags["schema"] = True

    return flags
```

`propose_target` should accept `phase_dir` argument and call
`detect_phase_changes` internally when caller doesn't pass `phase_changes`.

