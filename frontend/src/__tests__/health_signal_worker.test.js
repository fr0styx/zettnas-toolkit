import { describe, expect, it } from 'vitest';
import worker, { isoWeek, validate } from '../../../tools/health-signal-worker/src/index.js';

const GOOD = {
  schema: 1,
  id: 'a'.repeat(32),
  version: '1.10.3',
  platform: 'unraid',
  arch: 'x86_64',
  variant: 'full',
  drives: '5-8',
  features: ['ups', 'containers'],
};

function fakeDb() {
  const rows = new Map();
  return {
    rows,
    prepare(sql) {
      return {
        bind(...args) {
          return {
            async run() {
              if (sql.startsWith('INSERT')) {
                const [id, week, version, platform, arch, variant, drives, features] = args;
                rows.set(`${id}|${week}`, { id, week, version, platform, arch, variant, drives, features });
              } else if (sql.startsWith('DELETE')) {
                for (const [k, r] of rows) if (r.week < args[0]) rows.delete(k);
              }
            },
            async all() {
              return { results: [...rows.values()].filter((r) => r.week === args[0]) };
            },
          };
        },
      };
    },
  };
}

const post = (body, extra = {}) =>
  new Request('https://h.example/v1/report', { method: 'POST', body: typeof body === 'string' ? body : JSON.stringify(body), ...extra });

describe('health signal receiver', () => {
  it('numbers ISO weeks', () => {
    expect(isoWeek(new Date(Date.UTC(2026, 9, 26)))).toBe('2026-W44');
    expect(isoWeek(new Date(Date.UTC(2021, 0, 3)))).toBe('2020-W53');
  });

  it('accepts only the allow-listed fields', () => {
    expect(validate(GOOD).row.features).toBe('containers,ups');
    expect(validate({ ...GOOD, hostname: 'nas' }).error).toBe('unknown field hostname');
    expect(validate({ ...GOOD, id: 'not-hex' }).error).toBe('bad id');
    expect(validate({ ...GOOD, features: ['keylogger'] }).error).toBe('bad features');
    expect(validate({ ...GOOD, schema: 2 }).error).toBe('unknown schema');
    expect(validate([1]).error).toBe('not an object');
  });

  it('stores one row per install per week and reports last week', async () => {
    const env = { DB: fakeDb() };
    const monday = new Date(Date.UTC(2026, 9, 19));
    expect((await worker.fetch(post(GOOD), env, {}, monday)).status).toBe(204);
    expect((await worker.fetch(post(GOOD), env, {}, monday)).status).toBe(204); // same week: replaced
    await worker.fetch(post({ ...GOOD, id: 'b'.repeat(32), platform: 'truenas' }), env, {}, monday);
    expect(env.DB.rows.size).toBe(2);
    const res = await worker.fetch(new Request('https://h.example/v1/stats'), env, {}, new Date(Date.UTC(2026, 9, 27)));
    const stats = await res.json();
    expect(stats.installs).toBe(2);
    expect(stats.platform).toEqual({ unraid: 1, truenas: 1 });
    expect(stats.features).toEqual({ containers: 2, ups: 2 });
  });

  it('refuses junk, oversized bodies and other paths', async () => {
    const env = { DB: fakeDb() };
    expect((await worker.fetch(post('{nope'), env)).status).toBe(400);
    expect((await worker.fetch(post({ ...GOOD, id: 'x' }), env)).status).toBe(400);
    expect((await worker.fetch(post('x'.repeat(3000)), env)).status).toBe(413);
    expect((await worker.fetch(new Request('https://h.example/'), env)).status).toBe(404);
  });

  it('forgets reports older than 26 weeks', async () => {
    const env = { DB: fakeDb() };
    await worker.fetch(post(GOOD), env, {}, new Date(Date.UTC(2026, 0, 5)));
    await worker.fetch(post({ ...GOOD, id: 'c'.repeat(32) }), env, {}, new Date(Date.UTC(2026, 9, 19)));
    await worker.scheduled({}, env, {}, new Date(Date.UTC(2026, 9, 26)));
    expect([...env.DB.rows.values()].map((r) => r.id)).toEqual(['c'.repeat(32)]);
  });
});
