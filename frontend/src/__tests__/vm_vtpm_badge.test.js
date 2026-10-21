import { describe, it, expect, vi, beforeEach } from 'vitest';
import { initVmManager, loadVmDashboard, openVmCreateModal } from '../components/vm-manager.js';
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

async function openCreateWith(kvm) {
  api.get.mockImplementation((url) => {
    if (url === '/api/vms/telemetry') return Promise.resolve({ kvm });
    if (url === '/api/vms') return Promise.resolve([]);
    if (url === '/api/vms/isos') return Promise.resolve([]);
    if (url === '/api/vms/bridges') return Promise.resolve(['br0']);
    return Promise.resolve({});
  });
  initVmManager();
  await loadVmDashboard();
  openVmCreateModal();
  return document.querySelector('#modal-vm-create .vm-tpm-badge');
}

describe('vTPM availability badge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="vm-desktop-icon"></div>';
    window._vmManagerInitialized = false;
  });

  it('warns when the host has no swtpm', async () => {
    const badge = await openCreateWith({ state: 'active', vtpm_available: false });
    expect(badge.classList.contains('unavailable')).toBe(true);
    expect(badge.textContent).toContain('swtpm not installed');
  });

  it('shows the Windows 11 badge when swtpm is available', async () => {
    const badge = await openCreateWith({ state: 'active', vtpm_available: true });
    expect(badge.classList.contains('unavailable')).toBe(false);
    expect(badge.textContent).toContain('Windows 11 Ready');
  });
});
