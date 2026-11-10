// NUX-15: the container inspector's markup uses classes from its own lazy sheet instead of
// inline styles; every state it can show still renders, with the classes in place.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  initContainerModal,
  openContainerInspector,
  switchContainerTab,
  startLogStream,
  stopLogStream,
  appendLogLine,
  _resetContainerModalForTesting,
} from '../components/container-modal.js';
import { api } from '../api.js';

const CID = 'c111222333444555666777888';

function details(over = {}) {
  return {
    cid: CID,
    overview: { id: CID.slice(0, 12), full_id: CID, name: 'jellyfin', image: 'img:latest', state: 'running', running: true, restart_policy: 'unless-stopped', network_mode: 'bridge' },
    resources: {},
    ports: [{ public_port: 8096, private_port: 8096, type: 'tcp', ip: '0.0.0.0' }, {}],
    mounts: [],
    env: [],
    ...over,
  };
}

const byId = (id) => document.getElementById(id);

describe('container inspector on classes (NUX-15)', () => {
  beforeEach(() => {
    _resetContainerModalForTesting();
    vi.restoreAllMocks();
  });
  afterEach(() => {
    stopLogStream();
    _resetContainerModalForTesting();
    vi.unstubAllGlobals();
  });

  it('says so when the details cannot be read', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('boom'));
    await openContainerInspector(CID, 'jellyfin');
    const msg = byId('ci-overview-loading').querySelector('.ci-crit');
    expect(msg.textContent).toContain('boom');
    await switchContainerTab('edit');
    expect(byId('cie-form-host').querySelector('.ci-crit-2').textContent).toContain('boom');
  });

  it('lists ports without a host side and the rows to change them', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(details());
    await openContainerInspector(CID, 'jellyfin');
    const ports = byId('ci-ports-content');
    expect(ports.querySelectorAll('.ci-proto-tag.ci-xs-box')).toHaveLength(2);
    expect(ports.querySelector('td .ci-muted').textContent).toBe('None');
    expect(ports.querySelectorAll('.ci-port-input')[1].dataset.proto).toBe('tcp');
    expect(ports.querySelectorAll('.ci-port-input')[1].value).toBe('');
  });

  it('explains an empty port list on the host network and on a bridge', async () => {
    for (const mode of ['host', 'bridge']) {
      _resetContainerModalForTesting();
      const d = details({ ports: [] });
      d.overview.network_mode = mode;
      vi.spyOn(api, 'get').mockResolvedValue(d);
      await openContainerInspector(CID, 'jellyfin');
      expect(byId('ci-ports-content').querySelector('.ci-muted-center-3').textContent.length).toBeGreaterThan(10);
    }
  });

  it('shows the log notes and swaps the live-log note for the first line', async () => {
    let logs = () => Promise.reject(new Error('no logs'));
    vi.spyOn(api, 'get').mockImplementation((url) => (url.includes('/logs') ? logs() : Promise.resolve(details())));
    await openContainerInspector(CID, 'jellyfin');
    await switchContainerTab('logs');
    const term = byId('ci-logs-terminal');
    expect(term.querySelector('.ci-logs-note.ci-crit-center').textContent).toContain('no logs');

    logs = () => Promise.resolve({ lines: [] });
    await switchContainerTab('logs');
    expect(term.querySelector('.ci-logs-note.ci-muted-center-2')).not.toBeNull();

    vi.stubGlobal('EventSource', class { close() {} });
    startLogStream(CID);
    expect(term.querySelector('.ci-logs-note')).not.toBeNull();
    appendLogLine({ ts: '2026-10-01T12:00:01Z', msg: 'hello', stream: 'stdout' });
    expect(term.querySelector('.ci-logs-note')).toBeNull();
    expect(term.textContent).toContain('hello');
  });

  it('builds the edit form, locked for Kiboto itself', async () => {
    for (const name of ['jellyfin', 'zettnas-toolkit']) {
      _resetContainerModalForTesting();
      const d = details();
      d.overview.name = name;
      vi.spyOn(api, 'get').mockResolvedValue(d);
      initContainerModal();
      await openContainerInspector(CID, name);
      await switchContainerTab('edit');
      const input = byId('cie-input-name');
      expect(input.classList.contains('ci-xs-9')).toBe(true);
      expect(input.disabled).toBe(name === 'zettnas-toolkit');
      expect(byId('cie-select-restart').disabled).toBe(name === 'zettnas-toolkit');
      expect(byId('cie-btn-add-port').disabled).toBe(name === 'zettnas-toolkit');
    }
  });
});
