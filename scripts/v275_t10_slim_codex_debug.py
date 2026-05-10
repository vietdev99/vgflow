"""v2.75.0 T10 — slim codex-skills/vg-debug/SKILL.md.

Pattern: same as scripts/v275_t5_slim_codex_specs.py.
Replaces inline <step name="X">...</step> blocks inside <process>...</process>
with slim routing entries that read from `_shared/debug/*.md`.
"""
from pathlib import Path
import re


DEBUG_GROUPS = [
    {
        "title": "### Preflight section (extracted v2.75.0 T6)",
        "shared": "_shared/debug/preflight.md",
        "steps": ["0_parse_and_classify"],
        "blurb": (
            "Includes 1 step: 0_parse_and_classify (parse the bug description "
            "from arguments, classify by surface area / severity / scope, "
            "decide single-phase vs multi-phase debug strategy)."
        ),
        "codex_note": None,
    },
    {
        "title": "### Discovery + hypothesize + fix (extracted v2.75.0 T7)",
        "shared": "_shared/debug/discovery-and-fix.md",
        "steps": ["1_discovery", "2_hypothesize_and_fix"],
        "blurb": (
            "Includes 2 steps: 1_discovery (locate the bug origin via grep / "
            "graph queries / log inspection — never apply fixes during "
            "discovery) and 2_hypothesize_and_fix (rank candidate root causes, "
            "implement smallest-impact fix, write minimal regression test)."
        ),
        "codex_note": None,
    },
    {
        "title": "### Verify + close (extracted v2.75.0 T8 — final)",
        "shared": "_shared/debug/verify-and-close.md",
        "steps": ["3_verify_and_loop", "4_complete"],
        "blurb": (
            "Includes 2 closing steps: 3_verify_and_loop (run regression + full "
            "test suite, loop back to discovery if a different failure surfaces "
            "— max 3 loops before escalating) and 4_complete (commit fix + test "
            "atomically, emit debug.completed telemetry, suggest next pipeline "
            "step)."
        ),
        "codex_note": (
            "CODEX NOTE: Step 4_complete's commit + telemetry emission must "
            "happen in the main Codex thread per the adapter contract above "
            "(Tool mapping table). Do not delegate to a Claude subagent."
        ),
    },
]


def slim_step_blocks(text: str, groups: list) -> str:
    step_to_group = {}
    for gi, g in enumerate(groups):
        for s in g["steps"]:
            step_to_group[s] = gi

    emitted = set()
    output_chunks = []
    pos = 0
    pattern = re.compile(r'<step name="([^"]+)">', re.MULTILINE)
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

        between = text[pos:m.start()]
        if last_known_group is not None and gi == last_known_group:
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
        Path("codex-skills/vg-debug/SKILL.md"), DEBUG_GROUPS
    )
    print(f"vg-debug: {before} -> {after} lines")


if __name__ == "__main__":
    main()
