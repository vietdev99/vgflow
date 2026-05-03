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

import { APIRequestContext, expect } from '@playwright/test';

export interface Assertion {
  path: string;
  op: 'contains' | 'equals' | 'matches' | 'not_contains';
  value_from: string;
  layer?: string;
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

export async function expectReadAfterWrite(
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
}
