import { describe, it, expect, vi, beforeEach } from 'vitest';
import { initVmManager, loadVmDashboard } from '../components/vm-manager.js';
import { api } from '../api.js';

vi.mock('../api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  auth: { hasToken: vi.fn().mockReturnValue(true) },
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const baseVm = (overrides = {}) => ({
  id: 'vm-1',
  name: 'ubuntu-prod',
  state: 'running',
  qemu_pid: 4242,
  os_family: 'linux',
  vcpus: 4,
  ram_gb: 8,
  disk_size_gb: 64,
  disk_format: 'qcow2',
  ip_address: '192.168.1.180',
  cpu_usage_pct: 10,
  ram_usage_pct: 25,
  ...overrides,
});

let vmsResponse = [];

function mockApi() {
  api.get.mockImplementation((url) => {
    if (url === '/api/vms') return Promise.resolve(vmsResponse);
    if (url === '/api/vms/isos') return Promise.resolve([]);
    if (url === '/api/vms/bridges') return Promise.resolve(['br0']);
    return Promise.resolve({});
  });
}

const card = (id) => document.querySelector(`#vm-grid [data-vm-id="${id}"]`);

describe('VM grid keyed reconciliation (AGENTS.md §1.3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="vm-desktop-icon"></div>';
    window._vmManagerInitialized = false;
    mockApi();
    initVmManager();
  });

  it('keeps the same card node and patches CPU/RAM in place on telemetry-only changes', async () => {
    vmsResponse = [baseVm()];
    await loadVmDashboard();
    const before = card('vm-1');
    const popover = before.querySelector('#vm-join-popover-vm-1');
    popover.style.display = 'block';

    vmsResponse = [baseVm({ cpu_usage_pct: 20, ram_usage_pct: 50 })];
    await loadVmDashboard();
    const after = card('vm-1');

    expect(after).toBe(before);
    expect(after.querySelector('#vm-join-popover-vm-1').style.display).toBe('block');
    const vals = after.querySelectorAll('.vm-telemetry-row .telemetry-val');
    expect(vals[0].textContent).toBe('20%');
    expect(vals[1].textContent).toBe('4.0 / 8 GB');
    expect(after.querySelector('.fill-cpu').style.width).toBe('80%');
    expect(after.querySelector('.fill-ram').style.width).toBe('50%');
  });

  it('rebuilds only the changed card and rebinds its buttons on a state change', async () => {
    vmsResponse = [baseVm(), baseVm({ id: 'vm-2', name: 'win11' })];
    await loadVmDashboard();
    const other = card('vm-2');

    vmsResponse = [baseVm({ state: 'stopped', qemu_pid: null }), baseVm({ id: 'vm-2', name: 'win11' })];
    await loadVmDashboard();

    expect(card('vm-2')).toBe(other);
    const startBtn = card('vm-1').querySelector('.btn-vm-start');
    expect(startBtn).not.toBeNull();
    expect(typeof startBtn.onclick).toBe('function');
    expect(card('vm-1').querySelector('.vm-telemetry-row')).toBeNull();
  });

  it('adds, removes and reorders cards by VM id', async () => {
    vmsResponse = [baseVm(), baseVm({ id: 'vm-2', name: 'win11' })];
    await loadVmDashboard();
    const kept = card('vm-2');

    vmsResponse = [baseVm({ id: 'vm-2', name: 'win11' }), baseVm({ id: 'vm-3', name: 'debian' })];
    await loadVmDashboard();

    const ids = [...document.querySelectorAll('#vm-grid [data-vm-id]')].map((c) => c.dataset.vmId);
    expect(ids).toEqual(['vm-2', 'vm-3']);
    expect(card('vm-1')).toBeNull();
    expect(card('vm-2')).toBe(kept);
  });

  it('shows the empty state when the last VM is removed', async () => {
    vmsResponse = [baseVm()];
    await loadVmDashboard();
    vmsResponse = [];
    await loadVmDashboard();

    expect(document.querySelectorAll('#vm-grid [data-vm-id]').length).toBe(0);
    expect(document.getElementById('vm-empty-state').style.display).toBe('block');
  });
});
