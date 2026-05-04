from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def repo_root(start: Path | None = None) -> Path:
    cwd = (start or Path.cwd()).resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            return Path(out).resolve()
    except Exception:
        pass
    return cwd


def _strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[1:i])
    return text


def _parse_scalar(value: str) -> Any:
    value = value.split("#", 1)[0].strip()
    value = value.strip("'\"")
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value == "":
        return ""
    return value


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    raw = _strip_frontmatter(config_path.read_text(encoding="utf-8", errors="ignore"))
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(raw) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped or stripped.startswith("-"):
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value:
            parent[key] = _parse_scalar(value)
        else:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
    return root


def cfg_get(config: dict[str, Any], dotted: str, default: Any = "") -> Any:
    cur: Any = config
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def _zero_pad_phase(value: str) -> str:
    major, dot, rest = value.partition(".")
    try:
        n = int(major)
    except ValueError:
        return value
    if n < 10:
        return f"{n:02d}{dot}{rest}" if dot else f"{n:02d}"
    return value


def resolve_phase_dir(phase: str, phases_dir: Path) -> Path:
    if not phase:
        raise ValueError("phase is required")
    candidates: list[Path] = []
    for token in (phase, _zero_pad_phase(phase)):
        exact = sorted(phases_dir.glob(f"{token}-*"))
        candidates.extend([p for p in exact if p.is_dir()])
        bare = phases_dir / token
        if bare.is_dir():
            candidates.append(bare)
    if not candidates:
        for token in (phase, _zero_pad_phase(phase)):
            candidates.extend([p for p in phases_dir.glob(f"{token}.*") if p.is_dir()])
    unique = []
    seen = set()
    for path in candidates:
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(path)
    if len(unique) == 1:
        return unique[0].resolve()
    if not unique:
        available = ", ".join(sorted(p.name for p in phases_dir.iterdir() if p.is_dir())[:10])
        raise FileNotFoundError(f"no phase dir for {phase!r}; available: {available}")
    names = ", ".join(p.name for p in unique)
    raise RuntimeError(f"ambiguous phase {phase!r}: {names}")


def parse_frontmatter(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^\s*([A-Za-z_][\w.-]*)\s*:\s*(.*?)\s*$", line)
        if m:
            out[m.group(1)] = str(_parse_scalar(m.group(2))).lower()
    return out


def detect_phase_profile(phase_dir: Path) -> str:
    fm = parse_frontmatter(phase_dir / "SPECS.md")
    profile = fm.get("profile", "")
    platform = fm.get("platform", "")
    if profile in {"infra", "hotfix", "bugfix", "migration", "docs", "cli-tool", "library"}:
        return profile
    if platform in {"cli-tool", "library"}:
        return platform
    if not (phase_dir / "SPECS.md").exists():
        return "unknown"
    return "feature"


def phase_profile_skip_artifacts(profile: str) -> str:
    mapping = {
        "cli-tool": "UI-SPEC.md UI-MAP.md RUNTIME-MAP.json",
        "library": "API-CONTRACTS.md UI-SPEC.md UI-MAP.md RUNTIME-MAP.json",
        "infra": "TEST-GOALS.md API-CONTRACTS.md CONTEXT.md RUNTIME-MAP.json",
        "docs": "CONTEXT.md PLAN.md API-CONTRACTS.md TEST-GOALS.md RUNTIME-MAP.json SUMMARY.md",
    }
    return mapping.get(profile, "")


@dataclass
class VGEnv:
    repo_root: Path
    config_path: Path
    config: dict[str, Any]
    phase_number: str
    planning_dir: Path
    phases_dir: Path
    phase_dir: Path
    profile: str
    phase_profile: str
    python_bin: str

    @property
    def phase_dir_name(self) -> str:
        return self.phase_dir.name

    def as_dict(self) -> dict[str, Any]:
        return {
            "REPO_ROOT": str(self.repo_root),
            "PYTHON_BIN": self.python_bin,
            "PLANNING_DIR": str(self.planning_dir),
            "PHASES_DIR": str(self.phases_dir),
            "PHASE_NUMBER": self.phase_number,
            "phase_dir": self.phase_dir_name,
            "PHASE_DIR": str(self.phase_dir),
            "PROFILE": self.profile,
            "CONFIG_PROFILE": self.profile,
            "PHASE_PROFILE": self.phase_profile,
            "SKIP_ARTIFACTS": phase_profile_skip_artifacts(self.phase_profile),
            "VG_RUNTIME": "codex",
            "VG_ORCHESTRATOR": str(self.repo_root / ".claude" / "scripts" / "vg-orchestrator"),
        }

    def shell_exports(self) -> str:
        return "\n".join(
            f"export {key}={shlex.quote(str(value))}" for key, value in self.as_dict().items()
        )


def build_env(phase: str, start: Path | None = None) -> VGEnv:
    root = repo_root(start)
    config_path = root / ".claude" / "vg.config.md"
    config = load_config(config_path)
    planning_rel = cfg_get(config, "paths.planning_dir", cfg_get(config, "paths.planning", ".vg"))
    phases_rel = cfg_get(config, "paths.phases_dir", cfg_get(config, "paths.phases", f"{planning_rel}/phases"))
    planning_dir = (root / str(planning_rel)).resolve()
    phases_dir = (root / str(phases_rel)).resolve()
    phase_dir = resolve_phase_dir(phase, phases_dir)
    profile = str(cfg_get(config, "profile", "web-fullstack")).strip("'\"") or "web-fullstack"
    phase_profile = detect_phase_profile(phase_dir)
    return VGEnv(
        repo_root=root,
        config_path=config_path,
        config=config,
        phase_number=phase,
        planning_dir=planning_dir,
        phases_dir=phases_dir,
        phase_dir=phase_dir,
        profile=profile,
        phase_profile=phase_profile,
        python_bin=sys.executable,
    )


def dump_json(env: VGEnv) -> str:
    payload = env.as_dict()
    payload["config_path"] = str(env.config_path)
    return json.dumps(payload, indent=2, sort_keys=True)
