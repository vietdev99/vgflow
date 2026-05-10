<step name="5_mode_update">
## Step 5 (mode=update): Targeted update preserving existing data

Load existing FOUNDATION.md + PROJECT.md vào context.

AskUserQuestion: "Bạn muốn update phần nào?
- 'general' (mô tả tự nhiên thay đổi) → AI tự detect dimensions liên quan
- Hoặc chọn dimension cụ thể: platform / frontend / backend / data / auth / host / scale / compliance / requirements / milestone-N"

User answers + nói rõ thay đổi.

Model:
1. Identify affected dimensions (parse user input)
2. Load existing decisions F-XX cho dimensions đó (FOUNDATION namespace — không gian tên project-level)
3. Run mini-dialog (1-3 rounds) chỉ trên dimensions affected
4. Generate new F-(N+1) marked "supersedes F-XX"
5. **Preservation gate** (MERGE NOT OVERWRITE):
   - Write `FOUNDATION.md.staged` với chỉ dimensions changed updated
   - Other dimensions: copy verbatim từ existing
   - Run `difflib.SequenceMatcher` ≥ 80% similarity gate trên untouched sections
   - Fail gate → abort, original untouched, staged kept for review
6. If gate pass → atomic promote + commit

Cascade impact:
- If frontend/backend/build dimension changed → **⛔ forced user pause (destructive config change)**:
  Invoke `AskUserQuestion`:
    - header: "Re-derive config?"
    - question: "Tech stack đã thay đổi. Có muốn re-derive vg.config.md không? Nếu Yes, tôi sẽ chạy Round 6 để cập nhật model selection / port / crossai CLI cho fields vừa đổi. Nếu No, vg.config.md giữ nguyên (có thể drift sau này)."
    - options: ["Yes — re-derive affected fields", "No — keep current vg.config.md"]
  Không auto-advance trên silence. Chỉ chạy Round 6 khi user chọn Yes.
- Commit message: `project(update): <dimension(s)> changed — F-XX supersedes F-YY`
</step>

<step name="6_mode_milestone">
## Step 6 (mode=milestone): Append new milestone

Load existing PROJECT.md. Detect highest milestone number (search for `## Milestone X` headings).

AskUserQuestion: "Mô tả milestone mới (1-2 câu mục tiêu):"

User responds. Required field — không skip.

Model:
1. Parse description for **drift signals**:
   - Keywords: mobile/iOS/Android/native/desktop/Electron/serverless/lambda/embedded
   - If any match AND foundation.platform != matched type → **⛔ forced user pause (foundation drift risk)**:
     ```
     ⚠ Milestone description hint shift platform: 'mobile app' nhưng foundation = 'web-saas'.
        Đây có thể là foundation drift — workflow downstream sẽ nhầm platform target.
        Recommend: /vg:project --update foundation TRƯỚC khi tiếp tục.
     ```
     Invoke `AskUserQuestion`:
       - header: "Platform drift detected"
       - question: "Foundation hiện tại là 'web-saas' nhưng milestone mô tả nhắc đến 'mobile'. Bạn muốn làm gì?"
       - options:
         - "Stop — chạy /vg:project --update foundation trước (recommended)"
         - "Continue — milestone vẫn thuộc web-saas, từ 'mobile' chỉ là reference"
     Không auto-proceed. Chỉ append milestone khi user explicit chọn Continue.
2. If user chọn Continue → append `## Milestone {N+1}` section to PROJECT.md
3. FOUNDATION.md untouched (foundation = stable across milestones)
4. vg.config.md untouched
5. Commit: `project(milestone): add milestone {N+1} — {short title}`

Output: pointer to next step "Run /vg:roadmap để add phases cho milestone mới"
</step>

<step name="7_mode_rewrite">
## Step 7 (mode=rewrite): Destructive reset

Double confirm via AskUserQuestion:
```
"⛔ REWRITE = destructive. Existing PROJECT.md + FOUNDATION.md + vg.config.md sẽ được:
 - Backup → ${PLANNING_DIR}/.archive/{timestamp}/
 - Replaced với artifacts mới sau full re-run

 Confirm? [y] Yes — proceed / [n] No — abort"
```

If yes → second confirm:
```
"Last chance. Type 'rewrite-confirmed' để proceed."
```

If matched → execute:
```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="${ARCHIVE_DIR}/${TS}"
mkdir -p "$BACKUP_DIR"
[ -f "$PROJECT_FILE" ]    && cp "$PROJECT_FILE"    "$BACKUP_DIR/"
[ -f "$FOUNDATION_FILE" ] && cp "$FOUNDATION_FILE" "$BACKUP_DIR/"
[ -f "$CONFIG_FILE" ]     && cp "$CONFIG_FILE"     "$BACKUP_DIR/"

echo "🗄  Backed up to: ${BACKUP_DIR}"
rm -f "$PROJECT_FILE" "$FOUNDATION_FILE"
# Keep config but mark invalidated
[ -f "$CONFIG_FILE" ] && mv "$CONFIG_FILE" "$BACKUP_DIR/vg.config.md.pre-rewrite"
```

Then `MODE="first_time"` and re-enter step 4 (full 7-round flow).
</step>
