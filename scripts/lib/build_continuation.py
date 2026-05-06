from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "vg.build-continuation.v1"
TOKEN_NAME = ".build-continuation.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def token_path(phase_dir: Path) -> Path:
    return phase_dir / TOKEN_NAME


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def write_token(
    *,
    phase_dir: Path,
    phase: str,
    current_wave: int,
    max_wave: int,
    run_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    if current_wave >= max_wave:
        clear_token(phase_dir=phase_dir)
        return {}

    next_wave = current_wave + 1
    canonical = f"/vg:build {phase} --wave {next_wave} --resume"
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "pending",
        "command": "vg:build",
        "phase": phase,
        "phase_dir": str(phase_dir),
        "current_wave": current_wave,
        "next_wave": next_wave,
        "max_wave": max_wave,
        "canonical_command": canonical,
        "run_id": run_id,
        "session_id": session_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    _atomic_write_json(token_path(phase_dir), payload)
    return payload


def clear_token(*, phase_dir: Path) -> bool:
    path = token_path(phase_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


def load_token(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != SCHEMA or data.get("status") != "pending":
        return None
    if not data.get("canonical_command") or data.get("command") != "vg:build":
        return None
    return data


def find_pending_tokens(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    phase_root = root / ".vg" / "phases"
    if not phase_root.exists():
        return []
    out: list[tuple[Path, dict[str, Any]]] = []
    for path in phase_root.glob(f"*/{TOKEN_NAME}"):
        data = load_token(path)
        if data:
            out.append((path, data))
    out.sort(key=lambda item: item[0].stat().st_mtime, reverse=True)
    return out


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    stripped = stripped.lower().strip()
    stripped = re.sub(r"[.!?,;:]+$", "", stripped)
    return re.sub(r"\s+", " ", stripped)


CONTINUE_PHRASES = {
    "continue",
    "go on",
    "next",
    "resume",
    "ok",
    "okay",
    "yes",
    "tiep",
    "tiep tuc",
    "chay tiep",
    "lam tiep",
}


def is_continue_prompt(prompt: str) -> bool:
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    if len(lines) != 1:
        return False
    folded = _fold(lines[0])
    if len(folded) > 80:
        return False
    return folded in CONTINUE_PHRASES


def render_context(token: dict[str, Any], *, adapter: str = "auto") -> str:
    canonical = token["canonical_command"]
    phase = token.get("phase", "?")
    next_wave = token.get("next_wave", "?")
    max_wave = token.get("max_wave", "?")
    tasklist_line = (
        "For Codex, project/update the native plan from the new run's tasklist-contract.json "
        "and emit `vg-orchestrator tasklist-projected --adapter codex`."
        if adapter == "codex"
        else "Project the native tasklist from the new run's tasklist-contract.json and emit `vg-orchestrator tasklist-projected --adapter auto`."
    )
    return "\n".join(
        [
            "<vg-build-continuation>",
            "User prompt matched a pending VG build continuation token.",
            f"Canonical command: {canonical}",
            f"Phase: {phase}; next wave: {next_wave}/{max_wave}.",
            "You MUST continue the VG flow by invoking/executing this build command, not answer conversationally.",
            tasklist_line,
            "After the resumed partial wave finishes, use the next continuation token again until the final wave clears it.",
            "</vg-build-continuation>",
        ]
    )


def resolve_context(*, root: Path, prompt: str, adapter: str = "auto") -> str | None:
    if not is_continue_prompt(prompt):
        return None
    tokens = find_pending_tokens(root)
    if not tokens:
        return None
    _path, token = tokens[0]
    return render_context(token, adapter=adapter)
