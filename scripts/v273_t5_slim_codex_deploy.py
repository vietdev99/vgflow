"""v2.73.0 T5 — slim codex-skills/vg-deploy/SKILL.md.

Replaces inline <step name="X">...</step> blocks inside <process>...</process>
with slim routing entries that read from `_shared/deploy/*.md`.

Mirrors the v2.72.0 T7/T8 strategy used for vg-project / vg-migrate
(scripts/v272_slim_codex.py).
"""
from pathlib import Path
import re
import sys


DEPLOY_GROUPS = [
    {
        "title": "### Preflight section (extracted v2.73.0 T1)",
        "shared": "_shared/deploy/preflight.md",
        "steps": ["0_parse_and_validate", "0a_env_select_and_confirm"],
        "blurb": (
            "Includes 2 steps: 0_parse_and_validate (resolve phase dir, build-status "
            "gate, run-start, emit-tasklist, native tasklist projection) and "
            "0a_env_select_and_confirm (multi-select env picker + prod danger gate "
            "with --prod-confirm-token bypass)."
        ),
        "codex_note": (
            "CODEX NOTE: After preflight's primary actions complete (args parsed, "
            "tasklist projected, env selection persisted, prod gate satisfied), emit "
            "the HARD markers manually (Codex hook fallback):\n\n"
            "```bash\n"
            "\"${PYTHON_BIN:-python3}\" .claude/scripts/vg-orchestrator mark-step deploy 0_parse_and_validate\n"
            "\"${PYTHON_BIN:-python3}\" .claude/scripts/vg-orchestrator mark-step deploy 0a_env_select_and_confirm\n"
            "```"
        ),
    },
    {
        "title": "### Execute per-env (extracted v2.73.0 T2)",
        "shared": "_shared/deploy/execute.md",
        "steps": ["1_deploy_per_env"],
        "blurb": (
            "Includes 1 step: 1_deploy_per_env (sequential per-env deploy loop — "
            "resolve env config, spawn vg-deploy-executor per env, parse RESULT_JSON, "
            "narrate health, accumulate into deploy-results.json, ask user on failure). "
            "Per-env contract refs: `_shared/deploy/per-env-executor-contract.md` "
            "(spawn schema + post-spawn validation) and `_shared/deploy/overview.md` (flow)."
        ),
        "codex_note": (
            "CODEX NOTE: For per-env executor spawn, the source `Agent(subagent_type="
            "\"vg-deploy-executor\", ...)` call maps to `codex-spawn.sh --tier executor "
            "--sandbox workspace-write` (per codex_spawn_precedence table above — build "
            "executor row). Independent envs run sequentially (rule 2: shared SSH/DB "
            "contention); do NOT parallelize. After deploy loop completes, emit:\n\n"
            "```bash\n"
            "\"${PYTHON_BIN:-python3}\" .claude/scripts/vg-orchestrator mark-step deploy 1_deploy_per_env\n"
            "```"
        ),
    },
    {
        "title": "### Persist + close (extracted v2.73.0 T3 — final)",
        "shared": "_shared/deploy/persist-and-close.md",
        "steps": ["2_persist_summary", "complete"],
        "blurb": (
            "Includes 2 closing steps: 2_persist_summary (merge per-env results into "
            "DEPLOY-STATE.json deployed.{env} block via vg-deploy-merge-summary.py, "
            "preserve preferred_env_for / preferred_env_for_skipped, emit "
            "phase.deploy_completed telemetry) and complete (close native tasklist + "
            "run-complete). Post-deploy reflector trigger fires when "
            "meta_memory_mode != \"disabled\"."
        ),
        "codex_note": (
            "CODEX NOTE: After merge + summary persist and final close, emit the HARD "
            "markers + run-complete:\n\n"
            "```bash\n"
            "\"${PYTHON_BIN:-python3}\" .claude/scripts/vg-orchestrator mark-step deploy 2_persist_summary\n"
            "\"${PYTHON_BIN:-python3}\" .claude/scripts/vg-orchestrator mark-step deploy complete\n"
            "\"${PYTHON_BIN:-python3}\" .claude/scripts/vg-orchestrator run-complete 2>&1 | tail -1 || true\n"
            "```\n\n"
            "The terminal `vg-orchestrator run-complete` MUST be called by "
            "`_shared/deploy/persist-and-close.md`; on non-zero exit, fix evidence and "
            "retry per Stop hook parity contract above."
        ),
    },
]


def slim_step_blocks(text: str, groups: list) -> str:
    """Replace each step block listed in `groups` with a slim routing entry.

    Strategy:
    - Find the first <step ...> tag in the text.
    - Walk through groups in order; locate each step block by its name.
    - Replace each block with a routing comment + emit single composite entry per group.
    - Inter-step prose (e.g. `### Post-deploy reflector trigger` between step 2 and
      complete) is dropped because persist-and-close.md already covers it.
    """
    step_to_group = {}
    for gi, g in enumerate(groups):
        for s in g["steps"]:
            step_to_group[s] = gi

    emitted = set()
    output_chunks = []
    pos = 0
    pattern = re.compile(r'<step name="([^"]+)">', re.MULTILINE)

    # Track when we are between steps belonging to known groups so we can drop
    # interstitial prose that the shared file already owns.
    last_known_group = None

    while True:
        m = pattern.search(text, pos)
        if not m:
            output_chunks.append(text[pos:])
            break
        step_name = m.group(1)
        close_idx = text.find("</step>", m.end())
        if close_idx == -1:
            raise RuntimeError(f"Unclosed <step name='{step_name}'>")
        close_end = close_idx + len("</step>")

        gi = step_to_group.get(step_name)

        # Decide whether to keep the prose between the previous step and this one.
        between = text[pos:m.start()]
        if last_known_group is not None and gi == last_known_group:
            # Same group — drop interstitial prose (e.g. reflector trigger block
            # between step 2 and complete).
            pass
        else:
            output_chunks.append(between)

        if gi is None:
            output_chunks.append(text[m.start():close_end])
            last_known_group = None
        else:
            if gi not in emitted:
                g = groups[gi]
                steps_csv = ", ".join(g["steps"])
                routing = (
                    f"{g['title']}\n\n"
                    f"Read `{g['shared']}` and follow it exactly.\n"
                    f"{g['blurb']}\n\n"
                    f"Step coverage: {steps_csv}.\n"
                )
                if g.get("codex_note"):
                    routing += f"\n{g['codex_note']}\n"
                output_chunks.append(routing)
                emitted.add(gi)
            last_known_group = gi

        pos = close_end
        # Skip whitespace immediately after </step>
        while pos < len(text) and text[pos] == "\n":
            pos += 1
        output_chunks.append("\n")

    return "".join(output_chunks)


def slim_file(path: Path, groups: list) -> tuple[int, int]:
    original = path.read_text(encoding="utf-8")
    before = len(original.splitlines())
    new_text = slim_step_blocks(original, groups)
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    path.write_text(new_text, encoding="utf-8")
    after = len(new_text.splitlines())
    return before, after


def main() -> None:
    before, after = slim_file(
        Path("codex-skills/vg-deploy/SKILL.md"), DEPLOY_GROUPS
    )
    print(f"vg-deploy: {before} -> {after} lines")


if __name__ == "__main__":
    main()
