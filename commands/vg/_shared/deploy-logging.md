---
name: vg:_shared:deploy-logging
description: Deploy Logging (Shared Reference) — bọc SSH/bash commands trong /vg:build --sandbox + /vg:test --sandbox, append .deploy-log.txt per-phase, capture exit code + timing; input cho auto-draft RUNBOOK (C.1) + aggregators (C.4).
---

# Deploy Logging — Shared Helper (v1.14.0+ C.2)

Bọc mỗi lệnh SSH/bash ở giai đoạn triển khai (`/vg:build --sandbox`, `/vg:test --sandbox`) với logger tự động:

- Append **timestamp + tag + command** vào `.vg/phases/{phase}/.deploy-log.txt`.
- Capture **exit code** + **duration (giây)** mỗi lệnh.
- Ghi snapshot hạ tầng sau deploy thành công vào `.deploy-snapshot.txt` (cho RUNBOOK mục 7 — Infra state snapshot).

Đầu ra là nguồn duy nhất để:

1. **C.1 RUNBOOK auto-draft** — parser `vg_deploy_runbook_drafter.py` (step 7) đọc `.deploy-log.txt` → ghép thành các section 1-4 + 7 của DEPLOY-RUNBOOK.md.
2. **C.4 Aggregators** — `vg_deploy_aggregator.py` (step 8-9) merge mọi phase's `.deploy-log.txt` → DEPLOY-LESSONS + ENV-CATALOG + DEPLOY-FAILURE-REGISTER + DEPLOY-PERF-BASELINE + SMOKE-PACK.
3. **/vg:accept C.3** — prompt user review sections 1-4 + fill section 5 (Lessons); auto-detect pattern (chậm/retry/env-miss) từ log.

## Filesystem layout

```
.vg/phases/{phase}/
  ├── .deploy-log.txt          # append-only, mỗi lệnh 1 block 3-line
  ├── .deploy-snapshot.txt     # post-deploy infra state (node/pnpm/rust versions, pm2 jlist, df -h)
  └── DEPLOY-RUNBOOK.md        # drafted at accept by C.1 parser (step 7)
```

## Log format

Mỗi lệnh ghi 3 dòng, dễ parse bằng regex:

```
[2026-04-18T12:30:05Z] [ssh-build] BEGIN ssh vollx 'cd /home/vollx/vollxssp && pnpm build --filter api'
[2026-04-18T12:33:25Z] [ssh-build] END rc=0 duration=200s
[2026-04-18T12:33:25Z] [ssh-build] STDOUT_LAST_LINES:
  → Tasks:    3 successful, 3 total
  → Cached:   2 cached, 3 total
  → Time:     195.4s
```

- Dòng BEGIN: timestamp + tag + command gốc (unexpanded).
- Dòng END: timestamp + tag + `rc={exit_code}` + `duration={seconds}s`.
- (tuỳ chọn) block STDOUT_LAST_LINES: 5 dòng cuối stdout để lưu context hữu ích (build summary, service start message).

## API (bash, source từ lib/deploy-logging.sh)

```bash
source "${REPO_ROOT}/.claude/commands/vg/_shared/lib/deploy-logging.sh"

# Bắt buộc gọi 1 lần đầu session — khởi tạo log + header
deploy_log_init "${PHASE_DIR}"

# Wrap mỗi lệnh SSH/bash
deploy_exec "ssh-build"   "ssh vollx 'cd /home/vollx/vollxssp && pnpm turbo build --filter @vollxssp/api'"
deploy_exec "ssh-restart" "ssh vollx 'pm2 reload vollxssp-api --update-env'"
deploy_exec "health"      "curl -sf https://api.vollx.com/health"

# Sau deploy thành công — capture infra snapshot
deploy_log_snapshot "${PHASE_DIR}"

# Đóng log session (tuỳ chọn)
deploy_log_end "${PHASE_DIR}" "$OVERALL_RC"
```

## Exit-code semantics

`deploy_exec` trả về exit code của lệnh được wrap (propagate). Caller quyết định:

- `rc == 0` → continue.
- `rc != 0` → caller có thể retry, escalate, hoặc abort. Logger chỉ ghi, không tự quyết định.

Retry counter cho 1 tag duy nhất sẽ được aggregator phát hiện sau (C.4 DEPLOY-FAILURE-REGISTER → "env var missing, 3 retries before fix").

## Common tags (quy ước, không cứng)

| Tag | Dùng cho | Ví dụ |
|---|---|---|
| `ssh-pre` | Kiểm tra trước deploy (env var, disk) | `ssh vollx 'df -h /'` |
| `ssh-build` | Build remote | `ssh vollx 'pnpm build ...'` |
| `ssh-deploy` | Copy files / migrate | `rsync -az ...` |
| `ssh-restart` | Restart services | `pm2 reload ...` |
| `health` | Smoke check | `curl -sf .../health` |
| `rollback` | Revert | `ssh vollx 'git revert ...'` |

Tag do caller chọn — aggregator group theo tag + regex tên service.

## Tắt logging (cost/perf escape)

Khi `CONFIG_DEPLOY_LOGGING_ENABLED=false` (hoặc config `deploy.logging.enabled: false`), `deploy_exec` fallback thành `eval "$cmd"` trực tiếp, không ghi file. Dùng khi debug nhanh.

## Integration với /vg:build và /vg:test

Step sau (implementation steps 7+8) sẽ:
- Build `/vg:build --sandbox` step Deploy: replace raw `ssh vollx '...'` bằng `deploy_exec "ssh-deploy" "..."`.
- Test `/vg:test --sandbox`: tương tự cho smoke + restart sequence.

Step hiện tại (6) chỉ **tạo helper**, chưa wire. Wire là trách nhiệm step 7 (C.1 RUNBOOK structure) + step 10 (C.3 accept flow).
