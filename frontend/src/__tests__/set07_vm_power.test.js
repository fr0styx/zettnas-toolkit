// SET-07: a virtual machine's power. "Shut down" asks first and only asks the system inside;
// "Turn off now" and "Restart" are red questions; a card offers "Turn off now" during a shutdown
// only once the server says two minutes have passed.
import { describe, it, expect, beforeEach, vi } from 'vitest';

const plain = [];
const red = [];
vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn((title, msg, onOk, onCancel, options) => plain.push({ title, msg, onOk, options })),
  showDangerConfirm: vi.fn((title, msg, onOk, onCancel, options) => red.push({ title, msg, onOk, options })),
  showBottomSheet: vi.fn(),
}));

import {
  askPower,
  isOff,
  isShuttingDown,
  needsWatching,
  powerToast,
  shareReadOnly,
  shareRecord,
  shuttingDownActionsHtml,
  snapshotList,
} from '../components/vm/power.js';

describe('the questions before a power action', () => {
  beforeEach(() => {
    plain.length = 0;
    red.length = 0;
  });

  it('asks before Shut down, in plain colours, and says nothing is ended', () => {
    const run = vi.fn();
    askPower('stop', 'alpha', run);
    expect(run).not.toHaveBeenCalled();
    expect(plain).toHaveLength(1);
    expect(plain[0].title).toContain('alpha');
    expect(plain[0].msg).toContain('does not end it');
    expect(plain[0].options.destructive).toBe(false);
    plain[0].onOk();
    expect(run).toHaveBeenCalledTimes(1);
  });

  it('asks in red before Turn off now and before Restart', () => {
    const run = vi.fn();
    askPower('force_off', 'alpha', run);
    askPower('restart', 'alpha', run);
    expect(red.map((q) => q.title)).toEqual(['Turn off alpha now?', 'Restart alpha?']);
    expect(red[0].msg).toContain('pulling the plug');
    expect(red[1].msg).toContain('reset button');
    expect(run).not.toHaveBeenCalled();
  });

  it('starts, pauses and resumes without a question', () => {
    const run = vi.fn();
    for (const action of ['start', 'pause', 'resume']) askPower(action, 'alpha', run);
    expect(run).toHaveBeenCalledTimes(3);
    expect(plain.length + red.length).toBe(0);
  });
});

describe('what the page says and shows', () => {
  it('says "asked" while the machine still runs and "off" when it is off', () => {
    expect(powerToast('stop', 'shutting_down', 'alpha')).toEqual({ text: 'alpha was asked to shut down.', tone: 'info' });
    expect(powerToast('stop', 'stopped', 'alpha').text).toBe('alpha is off.');
    expect(powerToast('force_off', 'stopped', 'alpha').text).toBe('alpha was turned off.');
    expect(powerToast('start', 'running', 'alpha').text).toBe('alpha started.');
    expect(powerToast('restart', 'running', 'alpha').text).toBe('alpha was restarted.');
    expect(powerToast('pause', 'paused', 'alpha').text).toBe('alpha is paused.');
    expect(powerToast('resume', 'running', 'alpha').text).toBe('alpha runs again.');
    expect(powerToast('other', 'running', 'alpha').text).toContain('other');
  });

  it('offers nothing to press while a machine shuts down, then "Turn off now"', () => {
    const early = shuttingDownActionsHtml({ id: 'vm-1', state: 'shutting_down', turn_off_offered: false });
    expect(early).toContain('Shutting down');
    expect(early).not.toContain('<button');
    const late = shuttingDownActionsHtml({ id: 'vm-1', state: 'shutting_down', turn_off_offered: true });
    expect(late).toContain('data-act="force_off"');
    expect(late).toContain('Turn off now');
    expect(late).toContain('two minutes');
    expect(shuttingDownActionsHtml({ id: '"><b>', turn_off_offered: true })).not.toContain('"><b>');
  });

  it('knows which machines are off, and when the list needs reading again', () => {
    expect(isShuttingDown({ state: 'shutting_down' })).toBe(true);
    expect(isShuttingDown({ state: 'running' })).toBe(false);
    expect(['running', 'paused', 'shutting_down'].map((state) => isOff({ state }))).toEqual([false, false, false]);
    expect(isOff({ state: 'stopped' })).toBe(true);
    expect(isOff({})).toBe(true);
    expect(needsWatching([{ state: 'running' }, { state: 'shutting_down' }])).toBe(true);
    expect(needsWatching([{ state: 'running' }])).toBe(false);
    expect(needsWatching(null)).toBe(false);
  });

  it('reads the read-only choice under both saved names and saves it under both', () => {
    expect(shareReadOnly({ mode: 'ro' })).toBe(true);
    expect(shareReadOnly({ readonly: true })).toBe(true);
    expect(shareReadOnly({ mode: 'rw', readonly: false })).toBe(false);
    expect(shareReadOnly(undefined)).toBe(false);
    expect(shareRecord('/mnt/user/media', 'media', 'virtiofs', true)).toEqual({ host_path: '/mnt/user/media', mount_tag: 'media', driver: 'virtiofs', mode: 'ro', readonly: true });
    expect(shareRecord('/p', 't', '9p', false).mode).toBe('rw');
  });

  it('reads the list of snapshots as the server sends it', () => {
    expect(snapshotList([{ name: 'before-update' }])).toEqual([{ name: 'before-update' }]);
    expect(snapshotList({ snapshots: [{ name: 'old-shape' }] })).toEqual([{ name: 'old-shape' }]);
    expect(snapshotList(null)).toEqual([]);
  });
});
