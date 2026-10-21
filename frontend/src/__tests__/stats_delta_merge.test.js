import { describe, it, expect, beforeEach } from 'vitest';
import { state, mergeDockerTelemetry } from '../state.js';
import { statsView } from '../components/dashboard.js';

const container = (id, extra = {}) => ({
  id,
  name: `app-${id}`,
  state: 'running',
  cpu_pct: 1,
  mem_used: 100,
  status: 'Up 3 hours',
  ...extra,
});

const fullTick = () => ({
  cpu: { util: 5, temp: 40 },
  mem: { pct: 30 },
  layout: { version: 1 },
  events: [{ ts: 1, msg: 'boot' }],
  docker: [container('a'), container('b')],
});

describe('SSE live-stats deltas', () => {
  beforeEach(() => {
    state.latestStats = null;
  });

  it('mergeDockerTelemetry folds compact updates into the held list', () => {
    const current = { docker: [container('a'), container('b')] };
    const merged = mergeDockerTelemetry({ docker_tel: { a: { cpu_pct: 7.5 } } }, current);
    expect(merged.docker_tel).toBeUndefined();
    expect(merged.docker[0].cpu_pct).toBe(7.5);
    expect(merged.docker[0].name).toBe('app-a');
    expect(merged.docker[1]).toBe(current.docker[1]);
    expect(merged.docker[0]).not.toBe(current.docker[0]);
  });

  it('mergeDockerTelemetry leaves messages without docker_tel untouched', () => {
    const msg = { cpu: { util: 1 } };
    expect(mergeDockerTelemetry(msg, null)).toBe(msg);
  });

  it('setStats keeps omitted keys and applies container deltas', () => {
    state.setStats(fullTick());
    state.setStats({ cpu: { util: 9, temp: 40 } });
    state.setStats({ docker_tel: { b: { mem_used: 250, status: 'Up 4 hours' } } });

    expect(state.latestStats.cpu.util).toBe(9);
    expect(state.latestStats.mem.pct).toBe(30);
    expect(state.latestStats.layout.version).toBe(1);
    expect(state.latestStats.docker_tel).toBeUndefined();
    expect(state.latestStats.docker[1]).toMatchObject({ id: 'b', mem_used: 250, status: 'Up 4 hours', name: 'app-b' });
    expect(state.latestStats.docker[0].mem_used).toBe(100);
  });

  it('a full docker list replaces the held list (structural change)', () => {
    state.setStats(fullTick());
    state.setStats({ docker: [container('c')] });
    expect(state.latestStats.docker.map((c) => c.id)).toEqual(['c']);
  });

  it('statsView gives renderers full stats, with docker/events only when they changed', () => {
    state.setStats(fullTick());
    const raw = { cpu: { util: 9, temp: 40 } };
    state.setStats(raw);
    const view = statsView(raw);
    expect(view.cpu.util).toBe(9);
    expect(view.mem.pct).toBe(30);
    expect(view.layout.version).toBe(1);
    expect('docker' in view).toBe(false);
    expect('events' in view).toBe(false);

    const telRaw = { docker_tel: { a: { cpu_pct: 3 } } };
    state.setStats(telRaw);
    const telView = statsView(telRaw);
    expect(telView.docker[0].cpu_pct).toBe(3);
    expect('events' in telView).toBe(false);
  });

  it('statsView passes a full polling payload through intact', () => {
    const full = fullTick();
    state.setStats(full);
    const view = statsView(full);
    expect(view.docker.length).toBe(2);
    expect(view.events.length).toBe(1);
  });
});
