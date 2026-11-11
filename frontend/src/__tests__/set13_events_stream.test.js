// SET-13: the stream sends only the log entries that are new or changed; the list is kept by id.
import { describe, it, expect } from 'vitest';
import { state, mergeNewEvents, EVENTS_KEPT } from '../state.js';
import { statsView } from '../components/dashboard.js';

const entry = (id, more = {}) => ({ id, ts: 1000 + id, level: 'info', title: `Entry ${id}`, message: 'x', ...more });

describe('events_new', () => {
  it('adds a new entry at the top and keeps the list at its length', () => {
    const current = { events: Array.from({ length: EVENTS_KEPT }, (_, i) => entry(EVENTS_KEPT - i)) };
    const merged = mergeNewEvents({ events_new: [entry(101)], cpu: { util: 3 } }, current);
    expect(merged.events).toHaveLength(EVENTS_KEPT);
    expect(merged.events[0].id).toBe(101);
    expect(merged.events.at(-1).id).toBe(2); // the oldest went
    expect(merged.events_new).toBeUndefined();
    expect(merged.cpu).toEqual({ util: 3 });
  });

  it('a counted repeat replaces its entry and becomes the newest', () => {
    const current = { events: [entry(3), entry(2), entry(1)] };
    const merged = mergeNewEvents({ events_new: [entry(1, { count: 2, last_ts: 9000 })] }, current);
    expect(merged.events.map((e) => e.id)).toEqual([1, 3, 2]);
    expect(merged.events[0].count).toBe(2);
  });

  it('leaves a message without events_new alone, and works before any list is known', () => {
    const msg = { cpu: { util: 1 } };
    expect(mergeNewEvents(msg, { events: [entry(1)] })).toBe(msg);
    expect(mergeNewEvents(null, null)).toBeNull();
    expect(mergeNewEvents({ events_new: [entry(5)] }, null).events).toEqual([entry(5)]);
    expect(mergeNewEvents({ events_new: [entry(5)], events: [entry(4)] }, { events: [entry(1)] }).events.map((e) => e.id)).toEqual([5, 4]);
  });

  it('the page holds the merged list and the renderers are told that the log changed', () => {
    state.latestStats = null;
    state.setStats({ events: [entry(2), entry(1)], cpu: { util: 1 } });
    const raw = { events_new: [entry(3)] };
    expect(state.setStats(raw)).toBe(true);
    expect(state.latestStats.events.map((e) => e.id)).toEqual([3, 2, 1]);
    expect(statsView(raw).events.map((e) => e.id)).toEqual([3, 2, 1]);
    expect(statsView({ cpu: { util: 2 } }).events).toBeUndefined(); // "present only when it changed"
    state.latestStats = null;
  });
});
