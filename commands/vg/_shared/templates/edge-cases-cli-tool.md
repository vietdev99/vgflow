# Edge Cases Template — cli-tool profile

> For CLI tools (single-binary or scripts). Categories: args, stdin/stdout,
> env, TTY behavior, exit codes.

## Categories (5) — chọn relevant per goal

### 1. Argument parsing

| Type | Test |
|---|---|
| No args | Print usage + exit 0 (or 2 if "args required") |
| `--help` / `-h` | Print full help, exit 0 |
| `--version` / `-V` | Print version, exit 0 |
| Unknown flag | Reject with "unknown flag --foo" + suggestion ("did you mean --bar?") |
| Conflicting flags | E.g., `--verbose --quiet` → reject |
| Missing required arg | "Argument X required" + usage |
| Wrong type | `--count abc` (expected int) → 400-style error |
| Excess positional args | Reject OR ignore consistently |
| Repeated flag | First-wins / last-wins / accumulate (consistent per design) |
| Long form vs short | `--output` and `-o` equivalent |

### 2. Stdin / stdout / stderr

| Scenario | Test |
|---|---|
| Piped input (`cat file \| tool`) | Read from stdin OK |
| Interactive (TTY) input | Prompt user when expected |
| EOF early (`echo "" \| tool`) | Graceful — empty input → empty output (or error) |
| Large input (>1GB stream) | Stream-process, không OOM |
| Binary stdin | Either accept or reject with text-only hint |
| Stdout pipe to file | Plain output (no ANSI colors) |
| Stdout pipe to next cmd | Newline-delimited records, parseable |
| Stderr separate | Errors only on stderr, never stdout (preserves piping) |

### 3. Environment variables

| Edge | Test |
|---|---|
| Required env missing | Fail-fast với clear "set X=..." hint |
| Env wrong type | `PORT=abc` → 400 "PORT must be integer" |
| Env conflicts with flag | Flag wins (or env wins, but consistent + documented) |
| Unicode in env | Path with Unicode → handled |
| Path with spaces | Quote-handling correct |
| Empty env (`X=""`) | Treated as unset OR explicit empty (per design) |
| Sensitive env exposed in log | NEVER print API_KEY / TOKEN / SECRET in error |

### 4. TTY behavior

| Scenario | Test |
|---|---|
| Interactive TTY | Colors, progress bar, spinner |
| Piped output (no TTY) | No colors, no progress bar (just plain) |
| `--no-color` flag | Honored even on TTY |
| `NO_COLOR` env (universal) | Honored |
| Width unknown | Default 80 cols, no overflow |
| Resize mid-run | Re-render OR fixed width (consistent) |
| Ctrl-C (SIGINT) | Cleanup partial work, exit 130 |
| Ctrl-Z (SIGTSTP) | Suspend gracefully, resume on `fg` |

### 5. Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Generic error |
| 2 | Usage error (bad args) |
| 64-78 | sysexits.h conventions (optional) |
| 126 | Permission denied |
| 127 | Command not found |
| 128+N | Killed by signal N |

Per command, define exit-code table in CLI docs. Test each path:
- Happy path → 0
- Bad args → 2
- Soft fail (e.g., file not found, but expected) → 1
- Hard fail (corruption, panic) → 1 (or higher if conventional)
- Killed mid-write → 128+SIGTERM(15)=143

---

## Output format (per goal)

```markdown
# Edge Cases — G-03: Tool reads config file

## Argument parsing
| variant_id | input | expected_outcome | priority |
|---|---|---|---|
| G-03-a1 | `tool` (no args) | print usage, exit 2 | high |
| G-03-a2 | `tool --config /missing.toml` | "config not found" stderr, exit 1 | critical |

## Stdin / stdout
| variant_id | scenario | expected_outcome | priority |
|---|---|---|---|
| G-03-s1 | `cat valid.toml \| tool --stdin` | parse OK, exit 0 | high |
| G-03-s2 | piped to file (no TTY) | plain output, no ANSI | medium |
```

Variant IDs: `<goal_id>-<category_letter><N>`. Categories: a=arg, s=stdin/out,
e=env, t=tty, x=exit-code.

---

## Skip when not applicable

- Tool doesn't take input args (config-only) → skip 1 partial
- No interactive mode (always piped) → skip 4
- One-shot (no signals) → skip 4 signals

Document skip in section header.
