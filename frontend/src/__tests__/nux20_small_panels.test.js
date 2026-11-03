/** NUX-20: desktop shortcut titles, the disks list, events and listening ports read as translatable words. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { SYSTEM_SHORTCUTS } from '../components/desktop-shortcuts.js';
import { fetchAndRenderDisksInventory } from '../components/management/disks.js';
import { renderEventLog } from '../components/events.js';
import { renderListeningPortsTable, fetchListeningPorts } from '../components/network-manager.js';
import { api } from '../api.js';

const byId = (id) => document.getElementById(id);

describe('small panels (NUX-20)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('titles every system shortcut', () => {
    const titles = SYSTEM_SHORTCUTS.map((s) => s.title);
    for (const w of ['Apps & Containers', 'Storage & Chassis', 'Network & Virtual Switch', 'Activity & Telemetry', 'Hardware & Acoustic Profiles', 'UPS & Power Integrity', 'System & Security', 'Notifications & Alerts']) {
      expect(titles).toContain(w);
    }
  });

  it('says when no disks were found or the list could not load', async () => {
    document.body.innerHTML = '<table><tbody id="mgmt-disks-inventory-tbody"></tbody></table>';
    const req = vi.spyOn(api, 'request').mockResolvedValue({ ok: true, json: async () => ({ bays: [], nvme_slots: [] }) });
    await fetchAndRenderDisksInventory();
    expect(byId('mgmt-disks-inventory-tbody').textContent).toBe('No physical disks discovered.');
    req.mockRejectedValue(new Error('down'));
    await fetchAndRenderDisksInventory();
    expect(byId('mgmt-disks-inventory-tbody').textContent).toBe('Failed to load disks inventory.');
  });

  it('labels an event row', () => {
    document.body.innerHTML = '<div id="events-list"></div>';
    renderEventLog([{ ts: 1700000000, level: 'info', title: 'Pool scrub', message: 'Done' }]);
    const text = byId('events-list').textContent;
    expect(text).toContain('More Info');
    expect(text).toContain('▼ Details');
  });

  it('lists listening ports, or says why there are none', async () => {
    document.body.innerHTML = '<table><tbody id="net-listening-ports-tbody"></tbody></table>';
    renderListeningPortsTable([{ port: 22, proto: 'tcp', bind: '0.0.0.0', process: 'sshd' }]);
    expect(byId('net-listening-ports-tbody').textContent).toContain('Host System / Kernel');
    renderListeningPortsTable([{ port: 22, proto: 'tcp', process: 'sshd' }], 'nothing-like-this');
    expect(byId('net-listening-ports-tbody').textContent).toBe('No listening ports found matching filter.');
    vi.spyOn(api, 'get').mockRejectedValue(new Error('no route'));
    await fetchListeningPorts();
    expect(byId('net-listening-ports-tbody').textContent).toBe('Failed to load listening ports: no route');
  });
});
