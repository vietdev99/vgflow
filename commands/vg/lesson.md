---
description: Manual lesson capture — rare backup when reflector missed something. Drafts a candidate from user's text for later review.
argument-hint: "\"<lesson text>\""
mutates_repo: true
runtime_contract:
  must_emit_telemetry:
    - event_type: "lesson.started"
    - event_type: "lesson.completed"
---

# /vg:lesson

Capture a learning manually. **Rare backup** — primary flow is end-of-step reflection (`/vg:scope`, `/vg:review`, etc.) which auto-drafts candidates.

Use this when:
- Reflector missed a pattern you noticed
- You want to pre-emptively seed a rule before phase starts
- Recording a convention that doesn't come from any specific failure

## Load config

Read `.claude/commands/vg/_shared/config-loader.md` first.

## Input

`$ARGUMENTS` = free-form prose describing the lesson.

Examples:
- `/vg:lesson "build web phải dùng tsgo, tsc vanilla OOM"`
- `/vg:lesson "review step nếu có mutation phải reload verify data, không trust toast"`
- `/vg:lesson "khi touch apps/rtb-engine phải rebuild cargo không dùng pnpm"`

## Process

<step name="1_parse_intent">
Classify the lesson text into one of:
- `config_override` — user is naming a specific config key + value
- `rule` — user is describing behavior / pattern (most common)
- `unclear` — need to ask user for clarification

Heuristic: if text contains words like "dùng X thay Y", "use X instead of Y", "set X to Y", or references vg.config.md keys → likely `config_override`. Otherwise → `rule`.
</step>

<step name="2_draft_candidate">
Generate candidate YAML block:

```yaml
- id: L-{next_seq}
  source: user.lesson
  raw_text: "{user text}"
  type: {classified_type}
  title: "{short generated title, <80 chars}"
  scope:
    # AI infers from text:
    # - "build web" → step == "build" AND surfaces contains "web"
    # - "review với mutation" → step == "review" AND has_mutation == true
    any_of:
      - "{inferred predicate}"
  target_step: {build | review | scope | blueprint | global}
  action: {must_run | add_check | warn | suggest}
  proposed:
    # For config_override:
    key: "build_gates.typecheck_cmd"
    value: "pnpm tsgo --noEmit"
    # For rule:
    prose: |
      {generated prose from user text}
  confidence: 0.8  # user explicit, but AI inferring scope adds uncertainty
  evidence:
    - source: user_lesson
      timestamp: {iso_now}
      text: "{user text}"
  created_at: {iso_now}
```

Compute `dedupe_key = sha256(trigger + target)`:
```bash
echo -n "{trigger}|{target}" | sha256sum | cut -d' ' -f1
```

Check `REJECTED.md` for matching `dedupe_key` — if found ≥2 times → warn user "this was rejected before, still promote?".
</step>

<step name="3_append_candidates">
Append candidate block to `.vg/bootstrap/CANDIDATES.md` under `## Candidates`.

Emit telemetry:
```
emit_telemetry "bootstrap.candidate_drafted" PASS \
  "{\"id\":\"L-{seq}\",\"source\":\"user.lesson\",\"type\":\"{type}\"}"
```

Display to user:
```
📝 Lesson captured → CANDIDATES.md (L-{seq})

  Type: {type}
  Title: {title}
  Scope (AI inferred): {scope}
  Proposed: {target}

Next: /vg:learn --review L-{seq}
  Review evidence & dry-run before promote.
```
</step>

## Output

Single candidate written to `CANDIDATES.md`. User reviews + promotes via `/vg:learn`.
