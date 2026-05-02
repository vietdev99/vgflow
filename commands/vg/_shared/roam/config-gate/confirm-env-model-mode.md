# Config gate sub-step 4 — env + model + mode confirmation (AskUserQuestion 3-question batch)

**Marker:** `0a_confirm_env_model_mode`
**Source:** 3-question batch (42 lines) of original `0a_env_model_mode_gate`.

**MANDATORY FIRST ACTION** of this sub-step (before ANY other tool call) —
invoke `AskUserQuestion` with the 3-question payload below to lock down where
roam runs, which CLI executes, and whether to spawn or generate paste prompts.

## Skip AskUserQuestion ONLY when

- `${ARGUMENTS}` contains `--non-interactive`, OR
- `VG_NON_INTERACTIVE=1`, OR
- `${ARGUMENTS}` contains ALL THREE: `--target-env=<v>` (or `--local`/`--sandbox`/`--staging`/`--prod`), `--model=<v>`, AND `--mode=<v>`

When pre-fills exist (resume mode), the AI MUST tag the matching option's
label with `" (Recommended — prior run)"` so the user sees what was chosen
last time. Order options so the prior choice appears first.

## 3-question batch (single AskUserQuestion call)

```
questions:
  - question: "Roam env — chạy trên môi trường nào?"
    header: "Env"
    multiSelect: false
    options:
      # ⚠ Use envs.{local|sandbox|staging|prod}.decorated_label / .decorated_description
      # from .tmp/env-options.roam.json (written by enrich-env.md). Below is the FALLBACK shape only.
      - label: "local — máy của bạn"
        description: "Browser MCP local, port 3001-3010. Mặc định cho dogfood + nhanh."
      - label: "sandbox — VPS Hetzner (printway.work)"
        description: "Production-like, ssh deploy. Phù hợp khi muốn roam soi env gần production."
      - label: "staging — staging server"
        description: "Chỉ chọn nếu config có. Hiện chưa cấu hình → sẽ fail ở deploy."
      - label: "prod — production (CẢNH BÁO read-only)"
        description: "Workflow sẽ block mọi mutation lens (form-lifecycle, business-coherence)."
  - question: "Model — CLI nào sẽ chạy executor?"
    header: "Model"
    multiSelect: false
    options:
      - label: "Codex (gpt-5.3-codex, effort=high)"
        description: "Cheap + capable, default executor. Output dir: roam/codex/."
      - label: "Gemini 2.5 Pro"
        description: "UI consistency + a11y mạnh, cùng giá. Output dir: roam/gemini/."
      - label: "Council (cả Codex + Gemini song song)"
        description: "Ship-critical phase only — 2× cost, 2 perspectives. Output dirs: roam/codex/ + roam/gemini/."
  - question: "Mode — ai chạy executor?"
    header: "Mode"
    multiSelect: false
    options:
      # ⚠ AI MUST filter by .tmp/modes-avail.txt — only show options for which
      # tooling exists. Order: self first if available (cheapest, no subprocess),
      # then spawn, then manual.
      - label: "self — current Claude session là executor (Recommended cho web + MCP Playwright)"
        description: "AI session hiện tại điều khiển Playwright MCP trực tiếp. Không subprocess, không Chromium permission. Login + protocol thực hiện trong session. Output JSONL drop vào model dir. Phù hợp web platform khi MCP Playwright sẵn."
      - label: "spawn — VG tự subprocess CLI executor"
        description: "Cần codex hoặc gemini CLI authenticated. AI bị chặn nếu CLI không có. Risk macOS XPC permission cho Chromium binary. Output dir: roam/{model}/."
      - label: "manual — VG sinh INSTRUCTION.md + PASTE-PROMPT.md"
        description: "Copy đoạn paste-prompt sang CLI khác (Codex desktop, Cursor, web ChatGPT). User tự chạy, drop JSONL về dir đã chỉ, VG verify khi user signal continue."
```

## After AskUserQuestion returns (or skip-mode resolved CLI flags)

```bash
# Just write the marker — actual resolution + persistence is in persist-config.md
(type -t mark_step >/dev/null 2>&1 && mark_step "${PHASE_NUMBER}" "0a_confirm_env_model_mode" "${PHASE_DIR}") || touch "${PHASE_DIR}/.step-markers/0a_confirm_env_model_mode.done"
```

The 3 answers are picked up by `persist-config.md` via the env vars
`ROAM_ENV` / `ROAM_MODEL` / `ROAM_MODE` that AskUserQuestion writes
(or via CLI flags if --non-interactive).

Next: read `persist-config.md`.
