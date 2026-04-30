# CRUD Surfaces - Phase {PHASE}

Generated from: CONTEXT.md + API-CONTRACTS.md + TEST-GOALS.md + PLAN*.md

Purpose: make CRUD/resource behavior explicit before build. This file is the
resource-level contract that build, review, test, and accept must follow.

Rules:
- Use `base` for cross-platform requirements: roles, business flow, security,
  abuse, and performance.
- Use `platforms.web`, `platforms.mobile`, and `platforms.backend` only for the
  platforms touched by this phase. Do not copy web table rules into mobile.
- If a control is intentionally absent, write `"none: <reason>"`, not an empty
  value. Empty fields are treated as missing.
- For non-CRUD phases, still write a valid file with `"resources": []` and a
  `no_crud_reason`.

```json
{
  "version": "1",
  "generated_from": [
    "CONTEXT.md",
    "API-CONTRACTS.md",
    "TEST-GOALS.md",
    "PLAN.md"
  ],
  "no_crud_reason": "",
  "resources": [
    {
      "name": "Campaign",
      "domain_owner": "Marketing",
      "operations": ["list", "detail", "create", "update", "delete"],
      "scope": "owner-only",
      "expected_behavior": {
        "object_level": {
          "cross_owner_read": "403",
          "cross_tenant_read": "403",
          "cross_owner_mutation": "403",
          "state_lock": {"archived": "read-only", "published": "editable"}
        }
      },
      "base": {
        "roles": ["admin", "advertiser"],
        "business_flow": {
          "lifecycle_states": ["draft", "active", "paused", "archived"],
          "entry_points": ["campaign list", "campaign detail"],
          "invariants": [
            "Paused campaigns cannot spend budget",
            "Archived campaigns are read-only"
          ],
          "side_effects": ["audit log on create/update/delete"]
        },
        "security": {
          "object_auth": "org-scoped owner check on every object id",
          "field_auth": "server allowlist for writable fields",
          "csrf": "required for cookie-auth mutations, n/a for bearer-only API",
          "rate_limit": "per-user and per-IP mutation limits",
          "pii_policy": "mask or omit PII fields from list rows"
        },
        "abuse": {
          "enumeration_guard": "no sequential-id data leak across tenants",
          "bulk_action_limit": "bulk operations capped and audited",
          "replay_guard": "duplicate mutation guarded by idempotency when side effects exist"
        },
        "performance": {
          "api_p95_ms": 200,
          "list_max_page_size": 100,
          "indexed_queries": ["status", "created_at", "org_id"]
        },
        "accessibility": {
          "keyboard": "all interactive controls keyboard reachable",
          "focus": "focus visible and restored after modal close",
          "errors": "form errors associated with fields"
        },
        "delete_policy": {
          "confirm": true,
          "reversible_policy": "soft delete unless compliance requires hard delete",
          "audit_log": true
        }
      },
      "platforms": {
        "web": {
          "list": {
            "route": "/campaigns",
            "heading": "Campaigns",
            "description": "Manage campaign lifecycle and budget",
            "states": ["loading", "empty", "zero_result", "error", "unauthorized"],
            "data_controls": {
              "filters": ["status", "channel", "dateRange"],
              "search": {"url_param": "q", "debounce_ms": 300},
              "sort": {"default": "created_at desc", "columns": ["name", "status", "created_at"]},
              "pagination": {"url_param": "page", "size_param": "pageSize", "max_page_size": 100}
            },
            "table": {
              "columns": ["name", "status", "budget", "created_at", "actions"],
              "row_actions": ["view", "edit", "delete"],
              "bulk_actions": ["archive"]
            },
            "accessibility": {
              "table_headers": true,
              "aria_sort": true,
              "pagination_nav_label": true
            }
          },
          "form": {
            "create_route": "/campaigns/new",
            "update_route": "/campaigns/:id/edit",
            "fields": ["name", "status", "budget", "channel"],
            "validation": "client and server validation with field-level errors",
            "error_summary": true,
            "dirty_guard": true,
            "duplicate_submit_guard": true
          },
          "delete": {
            "confirm_dialog": true,
            "post_delete_state": "row removed and list count decremented"
          }
        },
        "mobile": {
          "list": {
            "screen": "CampaignList",
            "deep_link_state": true,
            "pull_to_refresh": true,
            "pagination_pattern": "infinite-scroll or load-more",
            "tap_target_min_px": 44,
            "states": ["loading", "empty", "zero_result", "error", "offline"],
            "network_error_state": true
          },
          "form": {
            "screen": "CampaignForm",
            "keyboard_avoidance": true,
            "native_picker_behavior": true,
            "submit_disabled_during_request": true,
            "offline_submit_policy": "block with retry message unless queueing is explicitly designed"
          },
          "delete": {
            "confirm_sheet": true,
            "undo_or_soft_delete_policy": "show undo if deletion is reversible"
          }
        },
        "backend": {
          "list_endpoint": {
            "path": "GET /api/campaigns",
            "pagination": {"strategy": "page-limit or cursor", "max_page_size": 100},
            "filter_sort_allowlist": ["status", "channel", "created_at"],
            "stable_default_sort": "created_at desc, id desc",
            "invalid_query_behavior": "400 with actionable error"
          },
          "mutation": {
            "paths": ["POST /api/campaigns", "PATCH /api/campaigns/{id}", "DELETE /api/campaigns/{id}"],
            "validation_4xx": true,
            "object_authz": true,
            "mass_assignment_guard": true,
            "idempotency": "required for payment/external side-effect mutations, n/a otherwise",
            "audit_log": true
          }
        }
      }
    }
  ]
}
```
