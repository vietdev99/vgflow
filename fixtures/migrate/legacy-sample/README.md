# Migrate self-test fixture (legacy-sample)

**Purpose:** deterministic test data for `/vg:migrate --self-test`. Verifies gate logic works on a known-good golden output WITHOUT spawning AI agents.

**Generic — no project-specific content.** Decisions/goals use abstract domain (CRUD API + form UI) so fixture works regardless of consumer project.

## Structure

```
legacy-sample/
├── input/                  ← Pre-migration GSD-flat format
│   ├── SPECS.md
│   ├── CONTEXT.md          (decisions only, no sub-sections)
│   ├── PLAN.md             (plain task list)
│   └── TEST-GOALS.md       (goals without Persistence/Surface)
├── expected/               ← Post-migration target (golden output)
│   ├── CONTEXT.md          (3 sub-sections per decision)
│   ├── PLAN.md             (with <file-path> + <goals-covered>)
│   ├── TEST-GOALS.md       (with **Persistence check:** + **Surface:**)
│   └── validation-report.txt  (expected step 9 stdout)
└── README.md
```

## Usage

```bash
/vg:migrate --self-test       # Runs gate logic on expected/, asserts all pass
```

**Behavior:** loads `expected/` files into temp dir, runs `verify-migrate-output.py` standalone validator, compares stdout vs `expected/validation-report.txt`. Exit 0 = gates working correctly. Exit 1 = gate logic broken.

## What this DOES NOT test

- AI agent spawn (Sonnet/Haiku) — that requires `--full-self-test` mode (future)
- Hallucination detection — fixture uses pre-validated content
- Real codebase scanning — uses synthetic decisions only

For end-to-end verification (AI spawn + real codebase): run `/vg:migrate <real_phase> --force` on a project phase.

## Maintenance

When adding new gates to `migrate.md` step 9:
1. Update `expected/` files to satisfy new gate
2. Update `validation-report.txt` to reflect new gate output
3. Re-run `/vg:migrate --self-test` to confirm
