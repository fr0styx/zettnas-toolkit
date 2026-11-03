/** ARC-26: the AI panel's sync and re-index progress displays, in every state. */
import { describe, it, expect, beforeEach } from 'vitest';
import { updateAiSyncProgressUi, updateAiReindexProgress } from '../components/management/ai.js';

const byId = (id) => document.getElementById(id);
const ids = (list, tag = 'span') => list.map((id) => `<${tag} id="${id}"></${tag}>`).join('');

describe('AI sync progress', () => {
  beforeEach(() => {
    document.body.innerHTML =
      ids(['ai-sync-state-badge', 'ai-sync-state-dot', 'ai-sync-state-text', 'ai-index-sync-state-pill', 'ai-index-current-path']) +
      ids(['btn-ai-sync-pause', 'btn-ai-sync-resume', 'btn-ai-sync-stop', 'btn-ai-index-pause', 'btn-ai-index-resume', 'btn-ai-index-stop'], 'button');
  });

  it.each([
    [{ state: 'running' }, '', 'Sync: Running', 'LEARNING', { 'btn-ai-sync-pause': 'inline-flex', 'btn-ai-sync-stop': 'inline-flex', 'btn-ai-sync-resume': 'none' }],
    [{ state: 'paused' }, '', 'Sync: Paused', 'PAUSED', { 'btn-ai-sync-resume': 'inline-flex', 'btn-ai-sync-pause': 'none' }],
    [{ state: 'stopped' }, '', 'Sync: Stopped', 'STOPPED', { 'btn-ai-sync-stop': 'none' }],
    [{ state: 'completed' }, '', 'Sync: Complete (Up to Date)', 'COMPLETE', {}],
    [{ indexed_files: 4 }, '', 'Sync: Complete (Up to Date)', 'COMPLETE', {}],
    [{ last_message: 'All synced' }, '', 'Sync: Complete (Up to Date)', 'COMPLETE', {}],
    [{}, 'disabled', 'Status: Disabled', 'DISABLED', {}],
    [{ enabled: false }, '', 'Status: Disabled', 'DISABLED', {}],
    [{}, '', 'Sync: Idle', 'IDLE', {}],
    [{}, 'warming', 'Sync: Idle', 'WARMING', {}],
  ])('%j / %s', (prog, status, text, pill, buttons) => {
    updateAiSyncProgressUi(prog, {}, status);
    expect(byId('ai-sync-state-text').textContent).toBe(text);
    expect(byId('ai-index-sync-state-pill').textContent).toBe(pill);
    for (const [id, display] of Object.entries(buttons)) expect(byId(id).style.display).toBe(display);
    expect(byId('ai-index-current-path').textContent.length).toBeGreaterThan(0);
  });

  it('the indexer buttons follow the state', () => {
    updateAiSyncProgressUi({ is_scanning: true });
    expect(byId('btn-ai-index-pause').disabled).toBe(false);
    expect(byId('btn-ai-index-resume').disabled).toBe(true);
    updateAiSyncProgressUi({ is_paused: true });
    expect(byId('btn-ai-index-resume').disabled).toBe(false);
    expect(byId('btn-ai-index-stop').disabled).toBe(false);
    updateAiSyncProgressUi({});
    expect(byId('btn-ai-index-stop').disabled).toBe(true);
  });

  it('copes without its elements', () => {
    document.body.innerHTML = '';
    expect(() => updateAiSyncProgressUi({ state: 'running' })).not.toThrow();
  });
});

describe('AI re-index progress', () => {
  const PARTS = ['ai-reindex-progress-container', 'ai-reindex-top-banner', 'ai-reindex-universal-strip', 'mgmt-sidebar-ai-badge', 'topbar-ai-accel-text',
    'ai-reindex-top-progress-bar', 'ai-reindex-top-pct-label', 'ai-reindex-top-chunks-label', 'ai-reindex-top-speed-label', 'ai-reindex-top-eta-label',
    'ai-reindex-univ-bar', 'ai-reindex-univ-pct', 'ai-reindex-univ-chunks', 'ai-reindex-univ-speed', 'ai-reindex-univ-eta',
    'ai-reindex-progress-bar', 'ai-reindex-pct-label', 'ai-reindex-speed-label', 'ai-reindex-eta-label', 'ai-reindex-chunks-label'];
  beforeEach(() => {
    document.body.innerHTML = ids(PARTS, 'div');
  });

  it('shows the share done, the speed and the time left', () => {
    updateAiReindexProgress({ status: 'running', completed: 250, total: 1000, speed: 12, eta_sec: 45 });
    expect(byId('ai-reindex-top-banner').style.display).toBe('block');
    expect(byId('ai-reindex-top-pct-label').textContent).toBe('25%');
    expect(byId('ai-reindex-univ-bar').style.width).toBe('25%');
    expect(byId('ai-reindex-top-eta-label').textContent).toBe('ETA: 45s');
    expect(byId('mgmt-sidebar-ai-badge').dataset.reindexing).toBe('1');
    updateAiReindexProgress({ status: 'running', percentage: 40, completed: 400, total: 1000, eta_sec: 150 });
    expect(byId('ai-reindex-univ-eta').textContent).toBe('ETA: 2m 30s');
    updateAiReindexProgress({ status: 'running', completed: 1, total: 1000, eta_sec: 7400 });
    expect(byId('ai-reindex-top-eta-label').textContent).toBe('ETA: 2h 3m');
    updateAiReindexProgress({ status: 'running', completed: 0, total: 0 });
    expect(byId('ai-reindex-top-eta-label').textContent).toBe('ETA: --');
  });

  it('hides everything when idle or done, and puts the badge back', () => {
    updateAiReindexProgress({ status: 'running', completed: 1, total: 2 });
    updateAiReindexProgress({ status: 'running', completed: 2, total: 2 });
    for (const id of ['ai-reindex-progress-container', 'ai-reindex-top-banner', 'ai-reindex-universal-strip']) expect(byId(id).style.display).toBe('none');
    expect(byId('mgmt-sidebar-ai-badge').textContent).toBe('NPU/GPU');
    updateAiReindexProgress(null);
    updateAiReindexProgress({ type: 'complete' });
    document.body.innerHTML = '';
    expect(() => updateAiReindexProgress({ status: 'running', completed: 1, total: 3 })).not.toThrow();
  });
});
