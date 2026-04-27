/**
 * filter-test-matrix.mjs — Phase 15 D-16 codegen matrix
 *
 * Defines the Filter + Pagination Test Rigor Pack:
 *   - 14 filter sub-cases (4 coverage + 3 stress + 3 state_integrity + 3 edge + 1 reserved buffer)
 *   - 18 pagination sub-cases (6 navigation + 2 url_sync + 4 envelope + 3 display + 2 stress + 1 mandatory edge)
 *
 * Each group maps to ONE template file under
 *   commands/vg/_shared/templates/{filter|pagination}-<group>.test.tmpl
 * Template renders as ONE spec file per (control × group) pair, containing
 * one `test(...)` block per sub-case. Total blocks per control = 14 (filter)
 * or 18 (pagination); files per control = 4 (filter groups) + 6 (pagination
 * groups) = 10.
 *
 * Validator (verify-filter-test-coverage.py) counts test() blocks whose name
 * contains the control slug — NOT files — to confirm matrix completeness.
 *
 * USAGE (called from /vg:test step 5d_codegen orchestrator):
 *   import {
 *     FILTER_GROUPS, PAGINATION_GROUPS,
 *     enumerateFilterFiles, enumeratePaginationFiles,
 *     renderTemplate,
 *   } from './filter-test-matrix.mjs'
 *
 *   const files = enumerateFilterFiles(goal, filterControl)  // [{slug, group, template_path, vars}]
 *   for (const f of files) {
 *     const body = await renderTemplate(f.template_path, f.vars)
 *     fs.writeFileSync(`${outDir}/${f.slug}.spec.ts`, body)
 *   }
 */
import fs from "node:fs/promises"
import path from "node:path"

// ─── matrix definitions ──────────────────────────────────────────────────────

export const FILTER_GROUPS = {
  coverage: [
    "cardinality_enum",
    "pairwise_combinatorial",
    "boundary_values",
    "empty_state",
  ],
  stress: [
    "toggle_storm",
    "spam_click_debounce",
    "in_flight_cancellation",
  ],
  "state-integrity": [
    "filter_sort_pagination",
    "url_sync",
    "cross_route_persistence",
  ],
  edge: [
    "xss_sanitize",
    "empty_result",
    "error_500_handling",
  ],
}

// 13 explicit sub-cases + 1 reserved buffer = 14 expected per D-16 lock.
export const FILTER_EXPECTED_TOTAL = 14
export const FILTER_RESERVED_SLOTS = 1

export const PAGINATION_GROUPS = {
  navigation: [
    "next",
    "prev",
    "first",
    "last",
    "jump_to_page",
    "page_size_dropdown",
  ],
  "url-sync": [
    "paste_query_reload",
    "filter_change_resets_page",
  ],
  envelope: [
    "meta_total",
    "meta_page",
    "meta_limit",
    "meta_has_next",
  ],
  display: [
    "x_y_of_z_label",
    "empty_single_page",
    "last_partial_page",
  ],
  stress: [
    "spam_next",
    "in_flight_cancel",
  ],
  edge: [
    "out_of_range_zero",            // mandatory
    // optional (cursor projects override via opts.includeOptional=true):
    "out_of_range_negative",
    "cursor_based_integrity",
  ],
}

// 6+2+4+3+2+1 mandatory = 18; +2 optional = 20 max
export const PAGINATION_EXPECTED_MANDATORY = 18
export const PAGINATION_EDGE_MANDATORY = ["out_of_range_zero"]
export const PAGINATION_EDGE_OPTIONAL = ["out_of_range_negative", "cursor_based_integrity"]

// ─── slug helpers ────────────────────────────────────────────────────────────

export function slugify(s) {
  return String(s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
}

// ─── enumeration ─────────────────────────────────────────────────────────────

/**
 * Enumerate the 4 filter group files for a single filter control.
 * Each file produces N test() blocks for its sub-cases.
 *
 * Returns Array<{slug, group, sub_cases, template_path, vars}>
 */
export function enumerateFilterFiles(goal, filterControl, opts = {}) {
  const goalSlug = slugify(goal.id || goal.goal_id)
  const ctrlName = String(filterControl.name || "filter")
  const ctrlSlug = slugify(ctrlName)
  const values = Array.isArray(filterControl.values) ? filterControl.values : []
  const out = []

  for (const [group, subs] of Object.entries(FILTER_GROUPS)) {
    out.push({
      slug: `${goalSlug}-${ctrlSlug}-filter-${group}`,
      group,
      sub_cases: subs.slice(),
      template_path: opts.templateRoot
        ? path.join(opts.templateRoot, `filter-${group}.test.tmpl`)
        : `filter-${group}.test.tmpl`,
      vars: {
        goal_id: goal.id || goal.goal_id,
        route: opts.route || goal.route || "/",
        role: opts.role || goal.actor || "admin",
        filter_name: ctrlName,
        filter_slug: ctrlSlug,
        filter_values_json: JSON.stringify(values),
        filter_value_count: values.length,
      },
    })
  }
  return out
}

/**
 * Enumerate the 6 pagination group files for a single pagination control.
 * Each file produces N test() blocks (mandatory only by default; pass
 * opts.includeOptional=true to add cursor + negative edge cases).
 */
export function enumeratePaginationFiles(goal, paginationControl, opts = {}) {
  const goalSlug = slugify(goal.id || goal.goal_id)
  const name = paginationControl.name || "pagination"
  const ctrlSlug = slugify(name)
  const includeOptional = !!opts.includeOptional
  const out = []

  for (const [group, allSubs] of Object.entries(PAGINATION_GROUPS)) {
    let subs = allSubs.slice()
    if (group === "edge" && !includeOptional) {
      subs = subs.filter((s) => PAGINATION_EDGE_MANDATORY.includes(s))
    }
    out.push({
      slug: `${goalSlug}-${ctrlSlug}-pagination-${group}`,
      group,
      sub_cases: subs,
      template_path: opts.templateRoot
        ? path.join(opts.templateRoot, `pagination-${group}.test.tmpl`)
        : `pagination-${group}.test.tmpl`,
      vars: {
        goal_id: goal.id || goal.goal_id,
        route: opts.route || goal.route || "/",
        role: opts.role || goal.actor || "admin",
        pagination_name: name,
        pagination_slug: ctrlSlug,
        page_size: paginationControl.page_size || 20,
        debounce_ms: paginationControl.debounce_ms || 300,
        type: paginationControl.type || "offset",
        include_optional: includeOptional,
      },
    })
  }
  return out
}

// ─── total counts (for validator cross-check) ────────────────────────────────

export function expectedFilterTestCount(filterControl) {
  // cardinality_enum is per-value; everything else is 1 test
  const values = Array.isArray(filterControl.values) ? filterControl.values.length : 0
  let total = values // cardinality_enum
  total += FILTER_GROUPS.coverage.length - 1 // pairwise + boundary + empty
  total += FILTER_GROUPS.stress.length
  total += FILTER_GROUPS["state-integrity"].length
  total += FILTER_GROUPS.edge.length
  return total // does not include reserved slot
}

export function expectedPaginationTestCount(paginationControl, opts = {}) {
  let total = 0
  total += PAGINATION_GROUPS.navigation.length
  total += PAGINATION_GROUPS["url-sync"].length
  total += PAGINATION_GROUPS.envelope.length
  total += PAGINATION_GROUPS.display.length
  total += PAGINATION_GROUPS.stress.length
  total += opts.includeOptional
    ? PAGINATION_GROUPS.edge.length
    : PAGINATION_EDGE_MANDATORY.length
  return total
}

// ─── template rendering ──────────────────────────────────────────────────────

/**
 * Render a Mustache-lite template:
 *   {{var.foo}}            → vars.foo (raw)
 *   {{#vars.flag}}…{{/vars.flag}}  → keep section if vars.flag truthy
 *
 * Returns rendered string.
 */
export async function renderTemplate(templatePath, vars) {
  const text = await fs.readFile(templatePath, "utf8")
  return renderString(text, vars)
}

export function renderString(text, vars) {
  // section blocks first (so they don't get mangled by var substitution)
  let out = text.replace(
    /\{\{#vars\.([a-zA-Z0-9_]+)\}\}([\s\S]*?)\{\{\/vars\.\1\}\}/g,
    (_, key, body) => (vars[key] ? body : ""),
  )
  // var substitutions
  out = out.replace(/\{\{var\.([a-zA-Z0-9_]+)\}\}/g, (_, key) => {
    const v = vars[key]
    return v == null ? "" : String(v)
  })
  return out
}
