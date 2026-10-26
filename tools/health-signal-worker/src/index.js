// ZettNAS health signal receiver (docs/HEALTH_SIGNAL.md). A Cloudflare Worker with a D1
// database; the free plan covers it.
//
//   POST /v1/report  one anonymous report per install per week (installs opt in)
//   GET  /v1/stats   totals for the last complete week, for anyone
//
// Stored per report: the random install id, the ISO week and the allow-listed fields below.
// The sender's IP address and headers are never stored. Rows older than 26 weeks are deleted
// by the weekly cron trigger.

export const MAX_BODY_BYTES = 2048;
export const KEEP_WEEKS = 26;
const FIELDS = {
  id: /^[0-9a-f]{32}$/,
  version: /^[0-9A-Za-z.+-]{1,32}$/,
  platform: /^[a-z0-9_]{1,24}$/,
  arch: /^[A-Za-z0-9_]{1,16}$/,
  variant: /^(full|core)$/,
  drives: /^(0|1-2|3-4|5-8|9-16|17\+)$/,
};
export const FEATURES = new Set(['containers', 'backups', 'ups', 'lcd', 'leds', 'ai', 'vms', 'sso']);

/** "2026-W43" for a date (ISO 8601 week, weeks start on Monday). */
export function isoWeek(date) {
  const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const day = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
  return `${d.getUTCFullYear()}-W${String(week).padStart(2, '0')}`;
}

/** The report as a database row, or an error. Unknown fields are refused, not stored. */
export function validate(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return { error: 'not an object' };
  if (body.schema !== 1) return { error: 'unknown schema' };
  const allowed = new Set([...Object.keys(FIELDS), 'schema', 'features']);
  for (const key of Object.keys(body)) if (!allowed.has(key)) return { error: `unknown field ${key}` };
  const row = {};
  for (const [key, pattern] of Object.entries(FIELDS)) {
    if (typeof body[key] !== 'string' || !pattern.test(body[key])) return { error: `bad ${key}` };
    row[key] = body[key];
  }
  const features = body.features ?? [];
  if (!Array.isArray(features) || features.length > FEATURES.size || !features.every((f) => FEATURES.has(f))) {
    return { error: 'bad features' };
  }
  row.features = [...new Set(features)].sort().join(',');
  return { row };
}

const json = (data, status = 200, extra = {}) =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', ...extra } });

async function handleReport(request, env, now) {
  const length = Number(request.headers.get('Content-Length') || 0);
  if (length > MAX_BODY_BYTES) return json({ error: 'too large' }, 413);
  const text = await request.text();
  if (text.length > MAX_BODY_BYTES) return json({ error: 'too large' }, 413);
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    return json({ error: 'not JSON' }, 400);
  }
  const { row, error } = validate(body);
  if (error) return json({ error }, 400);
  await env.DB.prepare(
    `INSERT OR REPLACE INTO reports (id, week, version, platform, arch, variant, drives, features)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
  )
    .bind(row.id, isoWeek(now), row.version, row.platform, row.arch, row.variant, row.drives, row.features)
    .run();
  return new Response(null, { status: 204 });
}

async function handleStats(env, now) {
  const lastWeek = isoWeek(new Date(now.getTime() - 7 * 86400000));
  const { results } = await env.DB.prepare(
    'SELECT version, platform, arch, variant, drives, features FROM reports WHERE week = ?'
  )
    .bind(lastWeek)
    .all();
  const count = (key) => {
    const out = {};
    for (const r of results) out[r[key]] = (out[r[key]] || 0) + 1;
    return out;
  };
  const features = {};
  for (const r of results) for (const f of (r.features || '').split(',').filter(Boolean)) features[f] = (features[f] || 0) + 1;
  return json(
    {
      week: lastWeek,
      installs: results.length,
      version: count('version'),
      platform: count('platform'),
      arch: count('arch'),
      variant: count('variant'),
      drives: count('drives'),
      features,
    },
    200,
    { 'Cache-Control': 'public, max-age=3600', 'Access-Control-Allow-Origin': '*' }
  );
}

export default {
  async fetch(request, env, ctx, now = new Date()) {
    const { pathname } = new URL(request.url);
    if (pathname === '/v1/report' && request.method === 'POST') return handleReport(request, env, now);
    if (pathname === '/v1/stats' && request.method === 'GET') return handleStats(env, now);
    return json({ error: 'not found' }, 404);
  },
  async scheduled(event, env, ctx, now = new Date()) {
    const oldest = isoWeek(new Date(now.getTime() - KEEP_WEEKS * 7 * 86400000));
    await env.DB.prepare('DELETE FROM reports WHERE week < ?').bind(oldest).run();
  },
};
