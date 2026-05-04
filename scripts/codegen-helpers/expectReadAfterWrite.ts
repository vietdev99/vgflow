/**
 * expectReadAfterWrite — Playwright test helper for read-after-write
 * verification (Task 22 invariant consumer).
 *
 * Generated specs MUST call this for every mutation step. AST validator
 * (verify-codegen-rcrurd-helper.py) confirms the call exists with the
 * correct invariant binding.
 *
 * Source of truth: schemas/rcrurd-invariant.schema.yaml
 */

import { APIRequestContext, Page, expect } from '@playwright/test';

export interface Assertion {
  path: string;
  op: 'contains' | 'equals' | 'matches' | 'not_contains';
  value_from: string;
  layer?: string;
}

export type UIAssertOpName =
  | 'count_matches_response_array'
  | 'text_contains_all'
  | 'each_exists_for_array_item'
  | 'text_equals_response_value'
  | 'text_matches_response_value'
  | 'visible_when_response_value'
  | 'hidden_when_response_value'
  | 'attribute_equals_response_value'
  | 'aria_state_matches'
  | 'input_value_equals_response';

export interface UIAssertOp {
  op: UIAssertOpName;
  dom_selector?: string;
  selector_template?: string;
  key_from?: string;
  response_path?: string;
  attribute?: string;
  aria_state?: string;
  regex?: string;
  expected_value?: unknown;
}

export interface UIAssertBlock {
  settle: { timeout_ms: number; poll_ms?: number };
  ops: UIAssertOp[];
}

export type LifecycleName = 'rcrurd' | 'rcrurdr' | 'partial';

export type PhaseName =
  | 'read_empty'
  | 'create'
  | 'read_populated'
  | 'update'
  | 'read_updated'
  | 'delete'
  | 'read_after_delete';

export interface LifecyclePhase {
  phase: PhaseName;
  write?: { method: 'POST' | 'PUT' | 'PATCH' | 'DELETE'; endpoint: string };
  read: {
    method: 'GET';
    endpoint: string;
    cache_policy: 'no_store' | 'cache_ok' | 'bypass_cdn';
    settle: { mode: 'immediate' | 'poll' | 'wait_event'; timeout_ms?: number; interval_ms?: number };
  };
  assert: Assertion[];
}

export interface RCRURDInvariant {
  goal_id: string;
  write: { method: 'POST' | 'PUT' | 'PATCH' | 'DELETE'; endpoint: string };
  read: {
    method: 'GET';
    endpoint: string;
    cache_policy: 'no_store' | 'cache_ok' | 'bypass_cdn';
    settle: { mode: 'immediate' | 'poll' | 'wait_event'; timeout_ms?: number; interval_ms?: number };
  };
  assert: Assertion[];
  precondition?: Assertion[];
  side_effects?: Assertion[];
  ui_assert?: UIAssertBlock;
  // Task 39 fields:
  lifecycle?: LifecycleName;
  lifecycle_phases?: LifecyclePhase[];
}

function evalJsonPath(body: unknown, path: string): unknown[] {
  if (path === '$') return [body];
  let cur: unknown[] = [body];
  const parts = path.startsWith('$.') ? path.slice(2).split('.') : [path.slice(1)];
  for (const part of parts) {
    const m = /^([^[]+)(\[\*])?$/.exec(part);
    if (!m) return [];
    const key = m[1];
    const star = !!m[2];
    const next: unknown[] = [];
    for (const c of cur) {
      if (c && typeof c === 'object' && key in (c as Record<string, unknown>)) {
        const v = (c as Record<string, unknown>)[key];
        if (star && Array.isArray(v)) next.push(...v);
        else next.push(v);
      }
    }
    cur = next;
  }
  return cur;
}

function resolveValue(valueFrom: string, payload: Record<string, unknown>): unknown {
  if (valueFrom.startsWith('literal:')) return valueFrom.slice(8);
  if (valueFrom.startsWith('action.')) return payload[valueFrom.slice(7)];
  return valueFrom;
}

function applyOp(observed: unknown[], op: string, expected: unknown): boolean {
  const flat = observed.flat();
  if (op === 'contains') return flat.includes(expected);
  if (op === 'not_contains') return !flat.includes(expected);
  if (op === 'equals') return observed.length === 1 && observed[0] === expected;
  if (op === 'matches') {
    return observed.length === 1 && typeof observed[0] === 'string'
      && new RegExp(String(expected)).test(observed[0]);
  }
  return false;
}

function cacheHeaders(policy: string): Record<string, string> {
  if (policy === 'no_store') return { 'Cache-Control': 'no-store, no-cache', Pragma: 'no-cache' };
  if (policy === 'bypass_cdn') return { 'Cache-Control': 'no-store', 'X-Bypass-CDN': '1' };
  return {};
}

/**
 * `page` is REQUIRED when invariant.ui_assert is set (Task 25 R9). Pass
 * `null` for backend-only goals (cron, worker, internal jobs) — the
 * helper throws R9_NO_PAGE if ui_assert is declared but page === null.
 */
export async function expectReadAfterWrite(
  page: Page | null,
  request: APIRequestContext,
  invariant: RCRURDInvariant,
  actionPayload: Record<string, unknown>,
): Promise<void> {
  const headers = cacheHeaders(invariant.read.cache_policy);

  if (invariant.precondition?.length) {
    const preResp = await request.get(invariant.read.endpoint, { headers });
    const preBody = await preResp.json().catch(() => ({}));
    for (const a of invariant.precondition) {
      const observed = evalJsonPath(preBody, a.path);
      const expected = resolveValue(a.value_from, actionPayload);
      expect(
        applyOp(observed, a.op, expected),
        `[${invariant.goal_id}] precondition failed: ${a.path} ${a.op} ${expected} (observed=${JSON.stringify(observed)})`,
      ).toBeTruthy();
    }
  }

  const writeResp = await request[invariant.write.method.toLowerCase() as 'post' | 'put' | 'patch' | 'delete'](
    invariant.write.endpoint, { data: actionPayload },
  );
  expect(
    writeResp.ok(),
    `[${invariant.goal_id}] write returned ${writeResp.status()} — R1 silent_state_mismatch suspected`,
  ).toBeTruthy();

  const readWithAssert = async (): Promise<{ allPassed: boolean; failures: string[] }> => {
    const readResp = await request.get(invariant.read.endpoint, { headers });
    const readBody = await readResp.json().catch(() => ({}));
    const failures: string[] = [];
    for (const a of invariant.assert) {
      const observed = evalJsonPath(readBody, a.path);
      const expected = resolveValue(a.value_from, actionPayload);
      if (!applyOp(observed, a.op, expected)) {
        failures.push(`${a.path} ${a.op} ${JSON.stringify(expected)} (observed=${JSON.stringify(observed).slice(0, 100)})`);
      }
    }
    return { allPassed: failures.length === 0, failures };
  };

  if (invariant.read.settle.mode === 'immediate') {
    const r = await readWithAssert();
    expect(
      r.allPassed,
      `[${invariant.goal_id}] R8 update_did_not_apply: ${r.failures.join('; ')}`,
    ).toBeTruthy();
  } else {
    const timeoutMs = invariant.read.settle.timeout_ms ?? 5000;
    const intervalMs = invariant.read.settle.interval_ms ?? 500;
    const deadline = Date.now() + timeoutMs;
    let last: { allPassed: boolean; failures: string[] } = { allPassed: false, failures: [] };
    while (Date.now() < deadline) {
      last = await readWithAssert();
      if (last.allPassed) break;
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    expect(
      last.allPassed,
      `[${invariant.goal_id}] R8 update_did_not_apply (after settle ${timeoutMs}ms): ${last.failures.join('; ')}`,
    ).toBeTruthy();
  }

  if (invariant.side_effects?.length) {
    const sideResp = await request.get(invariant.read.endpoint, { headers });
    const sideBody = await sideResp.json().catch(() => ({}));
    for (const a of invariant.side_effects) {
      const observed = evalJsonPath(sideBody, a.path);
      const expected = resolveValue(a.value_from, actionPayload);
      expect(
        applyOp(observed, a.op, expected),
        `[${invariant.goal_id}] side_effect ${a.layer} failed: ${a.path} ${a.op} ${expected}`,
      ).toBeTruthy();
    }
  }

  if (invariant.ui_assert) {
    if (page === null) {
      throw new Error(
        `[${invariant.goal_id}] R9_NO_PAGE: invariant has ui_assert but expectReadAfterWrite was called with page=null`,
      );
    }
    const { settle, ops } = invariant.ui_assert;
    const responseBodyForUI = await (await request.get(invariant.read.endpoint, { headers })).json().catch(() => ({}));

    for (const uop of ops) {
      await expect(async () => {
        await evalUIOp(page, uop, responseBodyForUI, actionPayload, invariant.goal_id);
      }).toPass({ timeout: settle.timeout_ms, intervals: [settle.poll_ms ?? 100] });
    }
  }
}


/**
 * Task 39: expectLifecycleRoundtrip — iterate lifecycle_phases for rcrurdr /
 * partial invariants, running write+read+assert per phase in sequence.
 *
 * When lifecycle is 'rcrurd' (or absent), delegates to expectReadAfterWrite.
 * Phases without a write spec (e.g. read_empty, read_populated) skip the write.
 */
export async function expectLifecycleRoundtrip(
  page: Page | null,
  request: APIRequestContext,
  invariant: RCRURDInvariant,
  actionPayload: Record<string, unknown>,
): Promise<void> {
  if (!invariant.lifecycle || invariant.lifecycle === 'rcrurd' || !invariant.lifecycle_phases?.length) {
    // Fall back to single-cycle helper for backward compat
    return expectReadAfterWrite(page, request, invariant, actionPayload);
  }

  for (const lp of invariant.lifecycle_phases) {
    const headers = cacheHeaders(lp.read.cache_policy);

    // Write step (skipped for read-only phases like read_empty, read_populated)
    if (lp.write) {
      const writeResp = await request[lp.write.method.toLowerCase() as 'post' | 'put' | 'patch' | 'delete'](
        lp.write.endpoint, { data: actionPayload },
      );
      expect(
        writeResp.ok(),
        `[${invariant.goal_id}] phase=${lp.phase} write returned ${writeResp.status()} — R1 silent_state_mismatch suspected`,
      ).toBeTruthy();
    }

    // Read + assert step
    const readWithPhaseAssert = async (): Promise<{ allPassed: boolean; failures: string[] }> => {
      const readResp = await request.get(lp.read.endpoint, { headers });
      const readBody = await readResp.json().catch(() => ({}));
      const failures: string[] = [];
      for (const a of lp.assert) {
        const observed = evalJsonPath(readBody, a.path);
        const expected = resolveValue(a.value_from, actionPayload);
        if (!applyOp(observed, a.op, expected)) {
          failures.push(
            `phase=${lp.phase}: ${a.path} ${a.op} ${JSON.stringify(expected)} ` +
            `(observed=${JSON.stringify(observed).slice(0, 100)})`
          );
        }
      }
      return { allPassed: failures.length === 0, failures };
    };

    if (lp.read.settle.mode === 'immediate') {
      const r = await readWithPhaseAssert();
      expect(
        r.allPassed,
        `[${invariant.goal_id}] R8 update_did_not_apply: ${r.failures.join('; ')}`,
      ).toBeTruthy();
    } else {
      const timeoutMs = lp.read.settle.timeout_ms ?? 5000;
      const intervalMs = lp.read.settle.interval_ms ?? 500;
      const deadline = Date.now() + timeoutMs;
      let last: { allPassed: boolean; failures: string[] } = { allPassed: false, failures: [] };
      while (Date.now() < deadline) {
        last = await readWithPhaseAssert();
        if (last.allPassed) break;
        await new Promise((r) => setTimeout(r, intervalMs));
      }
      expect(
        last.allPassed,
        `[${invariant.goal_id}] R8 update_did_not_apply (after settle ${timeoutMs}ms): ${last.failures.join('; ')}`,
      ).toBeTruthy();
    }

    // ui_assert keyed by apply_to_phase (Task 25 R9)
    if (invariant.ui_assert) {
      const uiBlock = invariant.ui_assert as UIAssertBlock & { apply_to_phase?: string };
      if (!uiBlock.apply_to_phase || uiBlock.apply_to_phase === lp.phase) {
        if (page === null) {
          throw new Error(
            `[${invariant.goal_id}] R9_NO_PAGE: invariant has ui_assert but expectLifecycleRoundtrip was called with page=null`,
          );
        }
        const responseBodyForUI = await (await request.get(lp.read.endpoint, { headers })).json().catch(() => ({}));
        for (const uop of uiBlock.ops) {
          await expect(async () => {
            await evalUIOp(page, uop, responseBodyForUI, actionPayload, invariant.goal_id);
          }).toPass({ timeout: uiBlock.settle.timeout_ms, intervals: [uiBlock.settle.poll_ms ?? 100] });
        }
      }
    }
  }
}


async function evalUIOp(
  page: Page,
  uop: UIAssertOp,
  responseBody: unknown,
  actionPayload: Record<string, unknown>,
  goalId: string,
): Promise<void> {
  const fail = (msg: string): never => {
    throw new Error(`[${goalId}] R9 ui_render_truth_mismatch (${uop.op}): ${msg}`);
  };

  if (uop.op === 'count_matches_response_array') {
    const arr = evalJsonPath(responseBody, uop.response_path!);
    const flat = arr.flat();
    const domCount = await page.locator(uop.dom_selector!).count();
    if (domCount !== flat.length) fail(`API has ${flat.length} items, DOM has ${domCount} at ${uop.dom_selector}`);
  } else if (uop.op === 'text_contains_all') {
    const arr = evalJsonPath(responseBody, uop.response_path!);
    const flat = arr.flat();
    const domText = await page.locator(uop.dom_selector!).innerText();
    for (const v of flat) {
      if (!domText.includes(String(v))) fail(`DOM ${uop.dom_selector} missing value ${JSON.stringify(v)}`);
    }
  } else if (uop.op === 'each_exists_for_array_item') {
    const arr = evalJsonPath(responseBody, uop.response_path!);
    const flat = arr.flat();
    for (const item of flat) {
      const keyVal = evalJsonPath(item, uop.key_from!)[0];
      if (keyVal === undefined) fail(`item missing key_from ${uop.key_from}`);
      const sel = uop.selector_template!.replace('{key}', String(keyVal));
      const cnt = await page.locator(sel).count();
      if (cnt !== 1) fail(`expected exactly 1 element at ${sel}, found ${cnt}`);
    }
  } else if (uop.op === 'text_equals_response_value') {
    const expected = evalJsonPath(responseBody, uop.response_path!)[0];
    const domText = (await page.locator(uop.dom_selector!).innerText()).trim();
    if (domText !== String(expected)) fail(`expected "${expected}", DOM shows "${domText}"`);
  } else if (uop.op === 'text_matches_response_value') {
    const domText = (await page.locator(uop.dom_selector!).innerText()).trim();
    if (!new RegExp(uop.regex!).test(domText)) fail(`DOM "${domText}" does not match /${uop.regex}/`);
  } else if (uop.op === 'visible_when_response_value' || uop.op === 'hidden_when_response_value') {
    const flagVal = evalJsonPath(responseBody, uop.response_path!)[0];
    const expected = uop.expected_value;
    const shouldBeVisible = (flagVal === expected) === (uop.op === 'visible_when_response_value');
    const isVisible = await page.locator(uop.dom_selector!).isVisible();
    if (isVisible !== shouldBeVisible) {
      fail(`expected ${shouldBeVisible ? 'visible' : 'hidden'} (response=${flagVal}, expected=${expected}), DOM ${isVisible ? 'visible' : 'hidden'}`);
    }
  } else if (uop.op === 'attribute_equals_response_value') {
    const expected = evalJsonPath(responseBody, uop.response_path!)[0];
    const actual = await page.locator(uop.dom_selector!).getAttribute(uop.attribute!);
    if (String(actual) !== String(expected)) fail(`${uop.attribute} expected ${expected}, DOM has ${actual}`);
  } else if (uop.op === 'aria_state_matches') {
    const expected = evalJsonPath(responseBody, uop.response_path!)[0];
    const actual = await page.locator(uop.dom_selector!).getAttribute(uop.aria_state!);
    if (String(actual) !== String(expected)) fail(`${uop.aria_state} expected ${expected}, DOM has ${actual}`);
  } else if (uop.op === 'input_value_equals_response') {
    const expected = evalJsonPath(responseBody, uop.response_path!)[0];
    const val = await page.locator(uop.dom_selector!).inputValue();
    if (val !== String(expected)) fail(`input.value expected ${expected}, DOM has ${val}`);
  }
}
