// =============================================================================
// VG INTERACTIVE-CONTROLS HELPER LIBRARY — REFERENCE TEMPLATE
// =============================================================================
//
// This file is a TEMPLATE shipped by the VG workflow harness (v2.7 Phase B).
//
// HOW TO USE
// ----------
//   1. Copy this file into your project's E2E helpers folder, e.g.
//        apps/web/e2e/helpers/interactive.ts
//   2. Make sure the import path matches what `/vg:test` step `5d_codegen`
//      writes into generated specs:
//        import { applyFilter, applySort, ... } from '../helpers/interactive';
//   3. The helper signatures + names below are part of a contract that the
//      `vg-codegen-interactive` skill assumes. Do NOT rename or change call
//      shapes — generated specs will fail to type-check or run.
//   4. Selector conventions (data-testid + data-row-* attributes) MUST be
//      honored by your UI components for the helpers to work. The VG review
//      phase enforces these via lint.
//
// WHO MAINTAINS WHAT
// ------------------
//   * VG harness owns: the contract (helper names, signatures, DSL grammar).
//   * Your project owns: the implementation lives in your repo, you can extend
//     internals (e.g., add retries, custom waits) but keep the public API.
//
// ASSERTION DSL — supported expression forms (see expectAssertion below):
//   1. rows[*].<field> === param
//   2. rows[*].<field>.includes(param)
//   3. rows[*].<field> in [<list>]
//   4. rows monotonically ordered by <field>
//   5. rows.length <= <N>
//
// Anything else throws `unsupported assertion: ${expr}` so the author writes
// a manual test.
// =============================================================================

import type { Page } from '@playwright/test';

export interface RowRecord {
  id: string;
  [field: string]: string;
}

export interface AssertionContext {
  param?: string;
  dir?: 'asc' | 'desc';
}

// -----------------------------------------------------------------------------
// applyFilter — click a filter dropdown + select a value
// -----------------------------------------------------------------------------
//
// Convention: filter UI exposes `[data-testid="filter-${name}"]` as the
// dropdown trigger, and the option list contains `[data-value="${value}"]`.
// After selection we wait for the URL to mutate (signal the app finished
// syncing search params).
export async function applyFilter(
  page: Page,
  name: string,
  value: string,
): Promise<void> {
  const trigger = page.locator(`[data-testid="filter-${name}"]`);
  await trigger.click();
  const option = page.locator(
    `[data-testid="filter-${name}"] [data-value="${value}"]`,
  ).first();
  // Fall back to a generic visible option if the dropdown is portal-rendered.
  if (await option.count() === 0) {
    await page.locator(`[data-value="${value}"]`).first().click();
  } else {
    await option.click();
  }
  await page.waitForFunction(
    (key) => new URL(window.location.href).searchParams.has(key),
    name,
    { timeout: 5000 },
  );
}

// -----------------------------------------------------------------------------
// applySort — click a sort header until aria-sort matches the requested dir
// -----------------------------------------------------------------------------
//
// Sort columns use `[data-testid="sort-${name}"]`. Convention: each click
// cycles the column through none → asc → desc → none. We click up to 3 times
// to reach the target direction, polling aria-sort.
export async function applySort(
  page: Page,
  name: string,
  dir: 'asc' | 'desc',
): Promise<void> {
  const header = page.locator(`[data-testid="sort-${name}"]`);
  for (let i = 0; i < 4; i++) {
    const aria = await header.getAttribute('aria-sort');
    if (aria === dir || aria === `${dir}ending`) {
      return;
    }
    await header.click();
  }
  throw new Error(
    `applySort: could not reach aria-sort="${dir}" on sort-${name} after 4 clicks`,
  );
}

// -----------------------------------------------------------------------------
// applyPagination — page-number, cursor, or page-size flavors
// -----------------------------------------------------------------------------
//
// Inputs:
//   { page: 2 }                — page-number nav: click `[data-testid="page-2"]`
//   { page: 2, pageSize: 50 }  — set the page-size select first, then nav
//   { next: 3 }                — cursor flavor: click `[data-testid="page-next"]` 3x
export async function applyPagination(
  page: Page,
  opts: { page?: number; pageSize?: number; next?: number },
): Promise<void> {
  if (typeof opts.pageSize === 'number') {
    const sel = page.locator('[data-testid="page-size"]');
    if (await sel.count() > 0) {
      await sel.selectOption(String(opts.pageSize));
    }
  }
  if (typeof opts.next === 'number' && opts.next > 0) {
    const btn = page.locator('[data-testid="page-next"]');
    for (let i = 0; i < opts.next; i++) {
      await btn.click();
    }
    return;
  }
  if (typeof opts.page === 'number') {
    const btn = page.locator(`[data-testid="page-${opts.page}"]`);
    await btn.click();
  }
}

// -----------------------------------------------------------------------------
// applySearch — fill a search box + press Enter
// -----------------------------------------------------------------------------
//
// Convention: search input is `[data-testid="search-${name}"]`. Caller is
// responsible for waiting out the debounce window — we deliberately do NOT
// add a waitForTimeout here so the spec stays explicit about timing.
export async function applySearch(
  page: Page,
  name: string,
  value: string,
): Promise<void> {
  const input = page.locator(`[data-testid="search-${name}"]`);
  await input.fill(value);
  await input.press('Enter');
}

// -----------------------------------------------------------------------------
// readUrlParams — flatten the current URL's search params into a plain object
// -----------------------------------------------------------------------------
export function readUrlParams(page: Page): Record<string, string> {
  return Object.fromEntries(new URL(page.url()).searchParams);
}

// -----------------------------------------------------------------------------
// readVisibleRows — read every visible `[data-testid="row-${id}"]`
// -----------------------------------------------------------------------------
//
// Convention: list rows expose `data-row-<field>="<value>"` attributes for
// every column the test cares about (status, type, name, created_at, etc.).
// Phase B-3 lint enforces this in /vg:review.
export async function readVisibleRows(page: Page): Promise<RowRecord[]> {
  const rows = page.locator('[data-testid^="row-"]');
  const count = await rows.count();
  const out: RowRecord[] = [];
  for (let i = 0; i < count; i++) {
    const row = rows.nth(i);
    const handle = await row.elementHandle();
    if (!handle) continue;
    const attrs = await handle.evaluate((el) => {
      const obj: Record<string, string> = {};
      for (const a of Array.from(el.attributes)) {
        if (a.name.startsWith('data-row-')) {
          obj[a.name.replace('data-row-', '')] = a.value;
        }
        if (a.name === 'data-testid') {
          const m = a.value.match(/^row-(.+)$/);
          if (m) obj.id = m[1];
        }
      }
      return obj;
    });
    out.push(attrs as RowRecord);
  }
  return out;
}

// -----------------------------------------------------------------------------
// expectAssertion — evaluate a DSL expression against rows + ctx
// -----------------------------------------------------------------------------
//
// Regex-dispatch (NOT eval) — the 5 supported forms are the only ones that
// pass. Anything else throws so the author writes a manual test instead.
const RE_EQUALS = /^rows\[\*\]\.([a-zA-Z_][a-zA-Z0-9_]*)\s*===\s*param$/;
const RE_INCLUDES =
  /^rows\[\*\]\.([a-zA-Z_][a-zA-Z0-9_]*)\.includes\(param\)$/;
const RE_IN_LIST =
  /^rows\[\*\]\.([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+\[(.+)\]$/;
const RE_ORDERED =
  /^rows\s+monotonically\s+ordered\s+by\s+([a-zA-Z_][a-zA-Z0-9_]*)$/;
const RE_LENGTH_LE = /^rows\.length\s*<=\s*(\d+)$/;

export async function expectAssertion(
  rows: RowRecord[],
  expr: string,
  ctx: AssertionContext,
): Promise<void> {
  const trimmed = expr.trim();

  let m = trimmed.match(RE_EQUALS);
  if (m) {
    const field = m[1];
    const param = ctx.param ?? '';
    for (const r of rows) {
      if (r[field] !== param) {
        throw new Error(
          `expectAssertion: row ${r.id ?? '?'}.${field}=${r[field]} !== ${param}`,
        );
      }
    }
    return;
  }

  m = trimmed.match(RE_INCLUDES);
  if (m) {
    const field = m[1];
    const param = (ctx.param ?? '').toLowerCase();
    for (const r of rows) {
      const v = (r[field] ?? '').toLowerCase();
      if (!v.includes(param)) {
        throw new Error(
          `expectAssertion: row ${r.id ?? '?'}.${field}="${r[field]}" does not include "${ctx.param}"`,
        );
      }
    }
    return;
  }

  m = trimmed.match(RE_IN_LIST);
  if (m) {
    const field = m[1];
    const list = m[2]
      .split(',')
      .map((s) => s.trim().replace(/^['"]|['"]$/g, ''));
    for (const r of rows) {
      if (!list.includes(r[field])) {
        throw new Error(
          `expectAssertion: row ${r.id ?? '?'}.${field}="${r[field]}" not in [${list.join(', ')}]`,
        );
      }
    }
    return;
  }

  m = trimmed.match(RE_ORDERED);
  if (m) {
    const field = m[1];
    const dir = ctx.dir ?? 'asc';
    for (let i = 1; i < rows.length; i++) {
      const a = rows[i - 1][field] ?? '';
      const b = rows[i][field] ?? '';
      const cmp = a < b ? -1 : a > b ? 1 : 0;
      if (dir === 'asc' && cmp > 0) {
        throw new Error(
          `expectAssertion: rows not asc-ordered by ${field} at index ${i} ("${a}" > "${b}")`,
        );
      }
      if (dir === 'desc' && cmp < 0) {
        throw new Error(
          `expectAssertion: rows not desc-ordered by ${field} at index ${i} ("${a}" < "${b}")`,
        );
      }
    }
    return;
  }

  m = trimmed.match(RE_LENGTH_LE);
  if (m) {
    const cap = Number(m[1]);
    if (rows.length > cap) {
      throw new Error(
        `expectAssertion: rows.length=${rows.length} > ${cap}`,
      );
    }
    return;
  }

  throw new Error(`unsupported assertion: ${expr}`);
}
