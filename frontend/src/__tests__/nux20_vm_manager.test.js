/** NUX-20: the VM manager window, the connect dialog and the KVM checks read as plain, translatable words. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  initVmManager,
  loadVmDashboard,
  openVmConnectModal,
  openKvmDiagnosticsModal,
  vmStateLabel,
  kvmChecks,
} from '../components/vm-manager.js';
import { api } from '../api.js';
import { showBottomSheet } from '../toast.js';

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

const TELEMETRY = {
  kvm: { state: 'active', badge: 'KVM Accelerated' },
  memory_budget: { total_host_ram_gb: 32, allocated_vm_ram_gb: 4, host_reserve_gb: 3.2, safe_headroom_gb: 24.8, safe_max_vm_ram_gb: 28.8 },
  cpu_capacity: { host_threads: 8, allocated_vcpus: 4, overcommit_ratio: 0.5, status: 'nominal' },
};

const VMS = [
  { id: 'v1', name: 'web1', state: 'running', vcpus: 4, ram_gb: 4, qemu_pid: 1234, ip_address: '192.168.1.50', vnc_port: 5902, description: 'Web server', boot_order: 'disk' },
  { id: 'v2', name: 'desk', state: 'running', vcpus: 2, ram_gb: 2, memory_mb: 4096 },
  { id: 'v3', name: 'idle', state: 'paused', vcpus: 1, ram_gb: 1 },
  { id: 'v4', name: 'setup', state: 'stopped', vcpus: 2, ram_gb: 2, iso_path: '/mnt/user/isos/debian.iso' },
];

async function openManager(vms = VMS) {
  api.get.mockImplementation(async (url) => {
    if (url === '/api/vms/telemetry') return TELEMETRY;
    if (url === '/api/vms') return vms;
    return [];
  });
  initVmManager();
  await loadVmDashboard();
  return document.getElementById('vm-grid');
}

const card = (grid, name) => grid.querySelector(`[data-vm-id="${VMS.find((v) => v.name === name).id}"]`);

describe('VM states and KVM checks in words (NUX-20)', () => {
  it('names each state, and keeps one it does not know', () => {
    expect(vmStateLabel('running')).toBe('Running');
    expect(vmStateLabel('PAUSED')).toBe('Paused');
    expect(vmStateLabel('shutoff')).toBe('Stopped');
    expect(vmStateLabel('crashed')).toBe('crashed');
    expect(vmStateLabel('')).toBe('Unknown');
    expect(vmStateLabel(undefined)).toBe('Unknown');
  });

  it('passes every check on a working host', () => {
    const checks = kvmChecks({ hardware_virt: true, module_loaded: true, device_present: true, device_writable: true });
    expect(checks.map((c) => c.text)).toEqual(['Supported', 'Loaded', 'Present', 'Allowed']);
    expect(checks.every((c) => c.tone === 'ok')).toBe(true);
  });

  it('says what is missing on a host without KVM', () => {
    const checks = kvmChecks({});
    expect(checks.map((c) => c.text)).toEqual(['Turned off in the BIOS', 'Module missing', 'Missing', 'Denied']);
    expect(checks.map((c) => c.tone)).toEqual(['crit', 'warn', 'crit', 'crit']);
    expect(kvmChecks({ amd_v: true, substate: 'container_restricted' })[3]).toMatchObject({ tone: 'warn', text: 'Blocked by the container (EPERM)' });
    expect(kvmChecks({ intel_vtx: true, cgroup_restricted: true })[0].text).toBe('Supported');
  });
});

describe('VM manager window (NUX-20)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="vm-desktop-icon"></div>';
    document.getElementById('vm-manager-window')?.remove();
    window._vmManagerInitialized = false;
  });

  it('shows the memory and thread budget in words', async () => {
    await openManager();
    expect(document.getElementById('vm-headroom-text').textContent).toBe('24.8 GB free for VMs (4 GB in use)');
    const win = document.getElementById('vm-manager-window').textContent;
    expect(win).toContain('Total memory:');
    expect(win).toContain('Safe limit for VMs:');
    expect(win).toContain('vCPU threads in use');
    expect(win).toContain('host threads');
    expect(win).toContain('ISO library');
  });

  it('labels each VM card by its state', async () => {
    const grid = await openManager();
    const web = card(grid, 'web1');
    expect(web.textContent).toContain('Running');
    expect(web.textContent).toContain('QEMU (1234)');
    expect(web.textContent).toContain('Disk');
    expect(web.textContent).toContain('vCPU load');
    expect(web.textContent).toContain('Memory used');
    expect(web.textContent).toContain('Connect to web1');
    expect(web.textContent).toContain('Port 5902');
    expect(web.textContent).toContain('All ways to connect…');
    expect(web.querySelector('.btn-copy-vnc').getAttribute('title')).toMatch(/^Copy the VNC address \(vnc:\/\/.+:5902\)$/);
    expect(web.querySelector('.btn-vm-join-toggle').textContent.trim()).toBe('Connect ▾');
    for (const word of ['Restart', 'Shut down', 'Force stop', 'Edit']) expect(web.querySelector('.vm-card-actions').textContent).toContain(word);

    const desk = card(grid, 'desk');
    expect(desk.textContent).toContain('QEMU active');
    expect(desk.textContent).toContain('Virtual machine');
    expect(desk.textContent).toContain('Display is on');
    expect(desk.textContent).toContain('Open console');

    const idle = card(grid, 'idle');
    expect(idle.textContent).toContain('Paused');
    expect(idle.textContent).toContain('QEMU paused');

    const setup = card(grid, 'setup');
    expect(setup.textContent).toContain('Stopped');
    expect(setup.textContent).toContain('QEMU stopped');
    expect(setup.textContent).toContain('ISO first');
    expect(setup.textContent).toContain('ISO inserted (debian.iso)');
  });

  it('offers the right actions in the More menu', async () => {
    const grid = await openManager();
    const labels = () => showBottomSheet.mock.calls.at(-1)[0].items.map((i) => i.label);

    card(grid, 'web1').querySelector('.btn-vm-more-sheet').click();
    expect(labels()).toEqual(expect.arrayContaining(['Restart VM', 'Shut down (ACPI)', 'Force stop (cuts the power)', 'Edit VM settings']));
    expect(showBottomSheet.mock.calls.at(-1)[0].subtitle).toBe('Running • 4 vCPU • 2048 MB');

    api.post.mockResolvedValue({});
    showBottomSheet.mock.calls.at(-1)[0].items.find((i) => i.label === 'Restart VM').onClick();
    expect(api.post).toHaveBeenCalledWith('/api/vms/v1/action', { action: 'restart' });

    card(grid, 'desk').querySelector('.btn-vm-more-sheet').click();
    expect(showBottomSheet.mock.calls.at(-1)[0].subtitle).toBe('Running • 2 vCPU • 4096 MB');

    card(grid, 'idle').querySelector('.btn-vm-more-sheet').click();
    expect(labels()).toEqual(expect.arrayContaining(['Shut down (ACPI)', 'Force stop (cuts the power)', 'Edit VM settings']));

    card(grid, 'setup').querySelector('.btn-vm-more-sheet').click();
    expect(labels()).toEqual(expect.arrayContaining(['Start VM', 'Edit VM settings']));

    const btn = card(grid, 'setup').querySelector('.btn-vm-more-sheet');
    btn.dataset.id = 'gone';
    btn.click();
    expect(showBottomSheet.mock.calls.at(-1)[0]).toMatchObject({ title: 'Virtual machine', subtitle: 'Stopped • 2 vCPU • 2048 MB' });
  });
});

describe('connect dialog and KVM checks (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('lists the ways to connect to a VM with an address', () => {
    openVmConnectModal('c1', {
      id: 'c1', name: 'files', state: 'running', ip_address: '10.0.0.9', vnc_port: 5903,
      host_shares: [{ host_path: '/mnt/user/data', mount_tag: 'data' }],
    });
    const text = document.getElementById('modal-vm-connect').textContent;
    expect(text).toContain('Connect to files');
    expect(text).toContain('Running');
    expect(text).toContain('IP: 10.0.0.9');
    expect(text).toContain('Console in the browser');
    expect(text).toContain('Open the desktop');
    expect(text).toContain('Serial terminal');
    expect(text).toContain('Copy VNC address');
    expect(text).toContain('Port 5903');
    expect(text).toContain('Port 3389');
    expect(text).toContain('ssh root@10.0.0.9');
    expect(text).toContain('10.0.0.9:3389');
    expect(text).toContain('Mount the shared folders (VirtIO-FS / 9p)');
    expect(document.querySelector('.btn-copy-mount-cmd').textContent).toBe('Copy');
    expect(document.getElementById('vm-connect-close').textContent.trim()).toBe('Close');
  });

  it('says when the VM has no address or name yet', () => {
    openVmConnectModal('c2', { id: 'c2' });
    const text = document.getElementById('modal-vm-connect').textContent;
    expect(text).toContain('Connect to Virtual machine');
    expect(text).toContain('Unknown');
    expect(text).toContain('No network address yet (waiting for DHCP)');
    expect(text).toContain('Waiting for the VM to get a network address');
    expect(text).toContain('Port 5900');
  });

  it('shows the KVM checks on a working host', () => {
    openKvmDiagnosticsModal({ state: 'active', hardware_virt: true, module_loaded: true, device_present: true, device_writable: true });
    const modal = document.getElementById('modal-kvm-diagnose');
    expect(modal.textContent).toContain('Virtualization checks (KVM)');
    expect(modal.textContent).toContain('KVM status');
    expect(modal.textContent).toContain('Hardware acceleration (KVM) is fully on.');
    expect(modal.textContent).toContain('4. The container may use /dev/kvm');
    expect(modal.textContent).not.toContain('How to fix it');
    expect(modal.querySelector('#kvm-diag-close').getAttribute('aria-label')).toBe('Close');
    expect(modal.innerHTML).toContain('var(--zn-text-ok)');
  });

  it('explains how to fix a container without /dev/kvm', () => {
    openKvmDiagnosticsModal({ state: 'restricted', badge: 'KVM blocked', cgroup_restricted: true });
    const modal = document.getElementById('modal-kvm-diagnose');
    expect(modal.textContent).toContain('KVM blocked');
    expect(modal.textContent).toContain('Virtualization is partly restricted.');
    expect(modal.textContent).toContain('Blocked by the container (EPERM)');
    expect(modal.textContent).toContain('How to fix it (Docker or Unraid container settings)');
    expect(modal.textContent).toContain('add the flag above under Extra Parameters');
    expect(modal.querySelector('#btn-copy-kvm-param').textContent).toBe('Copy');
    expect(modal.innerHTML).toContain('var(--zn-text-crit)');
    openKvmDiagnosticsModal({ state: 'restricted', remediation: 'Load the kvm module.' });
    expect(document.getElementById('modal-kvm-diagnose').textContent).toContain('Load the kvm module.');
  });
});
