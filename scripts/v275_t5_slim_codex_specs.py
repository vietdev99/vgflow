"""v2.75.0 T5 — slim codex-skills/vg-specs/SKILL.md.

Pattern: same as scripts/v274_t5_slim_codex_scope_review.py.
Replaces inline <step name="X">...</step> blocks inside <process>...</process>
with slim routing entries that read from `_shared/specs/*.md`.
"""
from pathlib import Path
import re


SPECS_GROUPS = [
    {
        "title": "### Preflight section (extracted v2.75.0 T1)",
        "shared": "_shared/specs/preflight.md",
        "steps": ["create_task_tracker", "parse_args", "check_existing"],
        "blurb": (
            "Includes 3 steps: create_task_tracker (prepare TodoWrite tracker "
            "for the SPECS workflow so progress is visible end-to-end), "
            "parse_args (parse {phase_number} positional + auto-discover phase "
            "directory and resolve naming/numbering), and check_existing "
            "(detect existing SPECS.md and ask before overwriting)."
        ),
        "codex_note": (
            "CODEX NOTE: TodoWrite is Claude-only. On Codex, follow the "
            "adapter contract above (Tool mapping table) — emit progress "
            "inline in the main thread instead of using TodoWrite."
        ),
    },
    {
        "title": "### Mode + guided + draft (extracted v2.75.0 T2)",
        "shared": "_shared/specs/mode-and-draft.md",
        "steps": ["choose_mode", "guided_questions", "generate_draft"],
        "blurb": (
            "Includes 3 steps: choose_mode (interactive choice between AI-draft "
            "vs guided vs hybrid mode), guided_questions (structured user "
            "questionnaire when guided mode is selected), and generate_draft "
            "(produce SPECS.md draft tailored to the chosen mode)."
        ),
        "codex_note": (
            "CODEX NOTE: Step choose_mode + guided_questions use AskUserQuestion "
            "on Claude. On Codex, ask the same options inline in the main thread "
            "per the adapter contract above (Tool mapping table)."
        ),
    },
    {
        "title": "### Write + interface standards + commit (extracted v2.75.0 T3 — final)",
        "shared": "_shared/specs/write-and-commit.md",
        "steps": [
            "write_specs",
            "write_interface_standards",
            "commit_and_next",
        ],
        "blurb": (
            "Includes 3 closing steps: write_specs (atomic write of "
            "${PHASE_DIR}/SPECS.md with required sections), "
            "write_interface_standards (emit INTERFACE-STANDARDS.md when the "
            "phase exposes API or UI surfaces), and commit_and_next (commit "
            "SPECS.md + INTERFACE-STANDARDS.md to git and route to /vg:scope)."
        ),
        "codex_note": None,
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
        Path("codex-skills/vg-specs/SKILL.md"), SPECS_GROUPS
    )
    print(f"vg-specs: {before} -> {after} lines")


if __name__ == "__main__":
    main()
