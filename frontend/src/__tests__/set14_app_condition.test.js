// SET-14: the list of apps says what state each app is in, and what the list itself is worth.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { setLanguage } from '../i18n.js';
import { actionSaid, appsSummary, bulkSaid, canResume, canRestart, canStart, canStop, conditionOf, conditionView, needsLook } from '../components/app-condition.js';
import { buildContainerRowInner, computeContainerRowSignature } from '../components/docker-table.js';
import { initContainersManager, loadContainersData, stopCwAutoRefresh, _resetCwAutoRefreshForTesting } from '../components/containers-manager.js';
import { DockManager } from '../components/dock.js';
import { api } from '../api.js';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn(), showDangerConfirm: vi.fn() }));

const app = (name, more = {}) => ({ id: name, name, image: `${name}:1`, state: 'running', status: 'Up 2 days', condition: 'running', ...more });
const PLEX = app('plex', { status: 'Up 2 days (unhealthy)', condition: 'unhealthy', needs_look: true, health: 'unhealthy' });
const LOOP = app('loop', { state: 'restarting', status: 'Restarting (1) 3 seconds ago', condition: 'restarting', restart_count: 14 });
const DEAD = app('radarr', { state: 'exited', status: 'Exited (1) 1 hour ago', condition: 'crashed', exit_code: 1, reason: 'exit_code' });
const OOM = app('ollama', { state: 'exited', status: 'Exited (137) 1 hour ago', condition: 'crashed', exit_code: 137, reason: 'out_of_memory' });
const OFF = app('sonarr', { state: 'exited', status: 'Exited (0) 1 hour ago', condition: 'stopped' });
const HELD = app('nzb', { state: 'paused', status: 'Up 2 hours (Paused)', condition: 'paused' });

describe('the state of one app', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('is one word with an icon, and why', async () => {
    expect(conditionView(app('ok'))).toMatchObject({ look: 'ok', icon: '✓', word: 'Running', why: '' });
    expect(conditionView(PLEX)).toMatchObject({ look: 'warn', word: 'Needs a look', why: 'It runs, but its own health check fails.' }); // it was green
    expect(conditionView(LOOP)).toMatchObject({ look: 'warn', word: 'Keeps restarting', why: 'It stops and is started again, 14 times so far.' });
    expect(conditionView(DEAD)).toMatchObject({ look: 'crit', word: 'Stopped unexpectedly', why: 'It ended by itself with error 1.' }); // quiet grey
    expect(conditionView(OOM).why).toBe('It was ended for using more memory than it may.');
    expect(conditionView(OFF)).toMatchObject({ look: 'muted', word: 'Stopped', why: '' });
    expect(conditionView(app('x', { state: 'exited', condition: 'stopped', reason: 'stopped_outside' })).why).toBe('It was stopped outside Kiboto.');
    expect(conditionView(app('x', { state: 'dead', condition: 'dead', exit_code: null })).why).toBe('It ended without anyone stopping it.');
    await setLanguage('de');
    expect(conditionView(DEAD).word).toBe('Unerwartet beendet');
    expect(conditionView(LOOP).why).toContain('14-mal');
  });

  it('a server from before gives the state and no alarm', () => {
    expect(conditionOf({ state: 'running' })).toBe('running');
    expect(conditionOf({ state: 'exited' })).toBe('stopped');
    expect(conditionOf({ state: 'paused' })).toBe('paused');
    expect(conditionOf({ state: 'something new' })).toBe('unknown');
    expect(conditionOf(null)).toBe('unknown');
    expect(needsLook({ state: 'exited' })).toBe(false);
    expect([PLEX, LOOP, DEAD, OOM].every(needsLook)).toBe(true);
  });

  it('offers what can be done with it', () => {
    expect([canStop(PLEX), canRestart(PLEX), canStart(PLEX)]).toEqual([true, true, false]);
    expect([canStop(LOOP), canRestart(LOOP), canStart(LOOP)]).toEqual([true, false, false]); // it had "Start" only
    expect([canStop(HELD), canResume(HELD), canStart(HELD)]).toEqual([true, true, false]);
    expect([canStop(DEAD), canStart(DEAD), canResume(DEAD)]).toEqual([false, true, false]);
    expect(canStart(app('x', { state: 'removing', condition: 'removing' }))).toBe(false);
  });

  it('a row shows the word, the reason and the right buttons', () => {
    const row = document.createElement('tr');
    const draw = (c) => {
      row.innerHTML = buildContainerRowInner(c, 'nas.local');
      return row;
    };
    expect(draw(PLEX).querySelector('.docker-condition').className).toContain('is-warn');
    expect(row.querySelector('.docker-state-badge').textContent.trim()).toBe('⚠ Needs a look');
    expect(row.querySelector('.docker-status-text').textContent).toBe('It runs, but its own health check fails.');
    expect(row.querySelector('.docker-condition').title).toBe('Up 2 days (unhealthy)'); // Docker's own words stay one hover away
    expect(row.querySelector('[data-action="stop"]')).toBeTruthy();
    expect(draw(HELD).querySelector('[data-action="unpause"]').title).toBe('Resume nzb');
    expect(row.querySelector('[data-action="start"]')).toBeNull();
    expect(draw(LOOP).querySelector('[data-action="stop"]')).toBeTruthy();
    expect(draw(DEAD).querySelector('[data-action="start"]')).toBeTruthy();
    expect(row.querySelector('[data-action="stop"]')).toBeNull();
    expect(draw(app('fine')).querySelector('.docker-status-text').textContent).toBe('Up 2 days');
    expect(computeContainerRowSignature(app('plex'))).not.toBe(computeContainerRowSignature(PLEX));
  });
});

describe('the sentence above the list', () => {
  it('says what is true of the apps', () => {
    expect(appsSummary([app('a'), app('b')])).toEqual({ look: 'ok', text: 'All 2 apps are running.' });
    expect(appsSummary([app('a')]).text).toBe('The app is running.');
    expect(appsSummary([app('a'), OFF]).text).toBe('1 of 2 apps are running; the others are stopped.');
    expect(appsSummary([app('a'), PLEX, LOOP])).toEqual({ look: 'warn', text: '2 apps need a look.' });
    expect(appsSummary([app('a'), PLEX, DEAD])).toEqual({ look: 'crit', text: '1 app stopped unexpectedly.' });
    expect(appsSummary([])).toEqual({ look: 'muted', text: 'No apps yet.' });
    expect(appsSummary(null).text).toBe('No apps yet.');
  });

  it('says what the list itself is worth', () => {
    expect(appsSummary([], { available: false }).text).toBe('Apps cannot run on this server: Docker was not found.');
    const stale = appsSummary([app('a')], { available: true, answering: false, stale: true, as_of: 1791394800 });
    expect(stale.look).toBe('crit');
    expect(stale.text).toMatch(/^Docker is not answering\. This list is from \d.* and may be out of date\.$/); // it stayed green
    expect(appsSummary([], { available: true, answering: false, stale: false }).text).toBe('Docker is not answering, so the apps cannot be listed right now.');
    expect(appsSummary([app('a')], { available: true, answering: true }).text).toBe('The app is running.');
    expect(appsSummary([app('a')], null, 'Permission denied')).toEqual({ look: 'crit', text: 'The list of apps could not be read: Permission denied' });
  });
});

describe('what an action says', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('is a sentence in each language, not a pasted action word', async () => {
    expect(actionSaid('stop', 'done', 'jellyfin')).toBe('jellyfin is stopped.'); // 'Container "jellyfin" successfully stoped.'
    expect(actionSaid('unpause', 'doing', 'jellyfin')).toBe('Resuming jellyfin…');
    expect(actionSaid('start', 'failed', 'jellyfin', 'port in use')).toBe('jellyfin could not be started: port in use');
    expect(actionSaid('something', 'done', 'x')).toBe('x was restarted.');
    expect(bulkSaid('stop', 'doing', { count: 3 })).toBe('Stopping 3 apps…'); // "Executing bulk stop on 3 containers..."
    expect(bulkSaid('pause', 'done', { successful: 2, total: 3 })).toBe('2 of 3 paused.');
    expect(bulkSaid('stop', 'failed', { error: 'no' })).toBe('That did not work: no');
    await setLanguage('de');
    expect(actionSaid('stop', 'done', 'jellyfin')).toBe('jellyfin ist gestoppt.'); // "jellyfin: stop erledigt"
    expect(bulkSaid('start', 'doing', { count: 1 })).toBe('1 App wird gestartet…');
  });
});

describe('the Apps window', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="os-dock-container"><div id="os-dock"></div></div>';
    window._containersManagerInitialized = false;
    window.DockManager = DockManager;
    DockManager.windows = {};
    _resetCwAutoRefreshForTesting();
    vi.restoreAllMocks();
    initContainersManager();
  });
  afterEach(() => {
    stopCwAutoRefresh();
    _resetCwAutoRefreshForTesting();
    vi.restoreAllMocks();
  });
  const chip = () => document.getElementById('cw-status-chip');
  const answers = (list, docker) => vi.spyOn(api, 'get').mockImplementation((url) => (url === '/api/docker/status' ? Promise.resolve(docker) : url === '/api/docker/containers' ? Promise.resolve(list) : Promise.resolve({})));

  it('says how the apps are, from what the server reports', async () => {
    answers([app('a'), PLEX], { available: true, answering: true });
    await loadContainersData();
    expect(chip().textContent.trim()).toBe('1 app needs a look.'); // "Docker Socket Active • Live Sync", whatever happened
    expect(chip().className).toContain('is-warn');
    expect(document.querySelectorAll('#cw-docker-containers-tbody .docker-condition')).toHaveLength(2);
  });

  it('says when there is no Docker, and when the list is an old one', async () => {
    answers([], { available: false, answering: false });
    await loadContainersData();
    expect(chip().textContent.trim()).toBe('Apps cannot run on this server: Docker was not found.');
    expect(document.getElementById('cw-docker-containers-tbody').textContent).toContain('Docker was not found');
    answers([app('a')], { available: true, answering: false, stale: true, as_of: 1791394800 });
    await loadContainersData();
    expect(chip().textContent).toContain('Docker is not answering');
    expect(chip().className).toContain('is-crit');
  });

  it('shows a list that could not be read as that, not as "no containers"', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => (url === '/api/docker/containers' ? Promise.reject(new Error('Permission denied')) : Promise.resolve(null)));
    await loadContainersData();
    expect(chip().textContent.trim()).toBe('The list of apps could not be read: Permission denied');
    expect(document.getElementById('cw-docker-containers-tbody').textContent).toContain('Permission denied');
  });
});
