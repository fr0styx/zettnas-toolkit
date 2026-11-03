/** NUX-20: Mission Control's virtual machines pane reads as translatable words. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { initManagement } from '../components/management.js';
import { api } from '../api.js';

const flush = () => new Promise((r) => setTimeout(r, 20));

describe('Mission Control VM pane (NUX-20)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('labels the summary, the VM cards and the KVM details', async () => {
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"></div></div></div>
      <span id="mgmt-hub-vms-pill"></span><span id="mgmt-sidebar-vms-badge"></span>
      <div id="mgmt-vms-summary-strip"></div><div id="mgmt-vms-grid"></div><div id="mgmt-vms-empty"></div><div id="mgmt-vms-kvm-body"></div>`;
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/vms/telemetry') return { kvm: { state: 'active' }, cpu: {}, memory_budget: {} };
      if (url === '/api/vms') return [{ id: 'a', name: 'web', state: 'running', vcpus: 2, ram_gb: 4 }, { id: 'b', name: 'db', state: 'stopped' }];
      return {};
    });
    vi.spyOn(api, 'post').mockResolvedValue({});
    try { initManagement(); } catch (_) { /* parts of the window this test doesn't build */ }
    window.dispatchEvent(new Event('vm-updated'));
    await flush();
    const text = document.body.textContent;
    expect(document.getElementById('mgmt-hub-vms-pill').textContent).toBe('1 Running');
    expect(document.getElementById('mgmt-sidebar-vms-badge').textContent).toBe('2 VMs');
    for (const w of ['HYPERVISOR ENGINE', 'MEMORY CEILING', 'vCPU OVERCOMMIT', '⏹ Stop', '▶ Start', 'Console', 'Hardware Virtualization Extension', 'CPU Host Threads', '8 Threads', 'vhost-net Acceleration', 'Default Network Bridge']) {
      expect(text).toContain(w);
    }
  });

  it('still renders without the hub pill, and for a VM without a name', async () => {
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"></div></div></div>
      <div id="mgmt-vms-summary-strip"></div><div id="mgmt-vms-grid"></div><div id="mgmt-vms-empty"></div><div id="mgmt-vms-kvm-body"></div>`;
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/vms' ? [{ id: 'vm-x', state: 'running' }] : {}));
    try { initManagement(); } catch (_) { /* as above */ }
    window.dispatchEvent(new Event('vm-updated'));
    await flush();
    expect(document.querySelector('.btn-vm-action-console').dataset.vmName).toBe('vm-x');
  });
});
