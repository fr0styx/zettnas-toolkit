import { describe, it, expect, vi, beforeEach } from 'vitest';
import { initVmManager, openVmEditModal } from '../components/vm-manager.js';
import { api } from '../api.js';

vi.mock('../api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  auth: { hasToken: vi.fn().mockReturnValue(true) },
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const GROUPS = {
  iommu_enabled: true,
  vfio_available: true,
  groups: [
    { group_id: 0, devices: [{ slot: '0000:00:00.0', class_code: '060000', name: 'Host bridge', driver: '', vfio_ready: false }] },
    { group_id: 2, devices: [{ slot: '0000:00:02.0', class_code: '030000', name: 'iGPU', driver: 'i915', vfio_ready: false }] },
    {
      group_id: 14,
      devices: [
        { slot: '0000:01:00.0', class_code: '030000', name: 'dGPU', driver: 'vfio-pci', vfio_ready: true },
        { slot: '0000:01:00.1', class_code: '040300', name: 'HDMI audio', driver: 'vfio-pci', vfio_ready: true },
      ],
    },
  ],
};

const flush = () => new Promise((r) => setTimeout(r, 0));

async function openEdit(vm, groups = GROUPS) {
  api.get.mockImplementation((url) => {
    if (url === '/api/vms/iommu-groups') return Promise.resolve(groups);
    if (url === '/api/vms/usb-devices') return Promise.resolve([]);
    return Promise.resolve([]);
  });
  api.put.mockResolvedValue({ ...vm });
  openVmEditModal(vm.id, vm);
  await flush();
  await flush();
  return document.getElementById('modal-vm-edit');
}

const baseVm = (extra = {}) => ({ id: 'vm-gpu', name: 'gaming', vcpus: 4, ram_gb: 8, state: 'stopped', boot_order: 'disk', ...extra });

describe('PCI / GPU passthrough card', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="vm-desktop-icon"></div>';
    window._vmManagerInitialized = false;
    initVmManager();
  });

  it('only lets vfio-pci devices be selected and hides bridges', async () => {
    const modal = await openEdit(baseVm());
    const checks = [...modal.querySelectorAll('.vm-pci-check')];
    expect(checks.map((c) => c.dataset.slot)).toEqual(['00:02.0', '01:00.0', '01:00.1']);
    expect(checks[0].disabled).toBe(true);
    expect(checks[1].disabled).toBe(false);
    expect(modal.querySelector('#vm-edit-pci-list').textContent).toContain('i915');
    expect(modal.querySelector('.vm-pci-group-note').textContent).toContain('14');
  });

  it('saves the selected devices as pci_passthrough', async () => {
    const modal = await openEdit(baseVm());
    const gpu = modal.querySelector('.vm-pci-check[data-slot="01:00.0"]');
    gpu.checked = true;
    gpu.onchange();
    await modal.querySelector('#vm-edit-submit').onclick();
    const payload = api.put.mock.calls[0][1];
    expect(payload.pci_passthrough).toEqual([{ slot: '01:00.0', name: 'GPU dGPU' }]);
  });

  it('keeps an already-attached device removable even if it is no longer on vfio-pci', async () => {
    const modal = await openEdit(baseVm({ pci_passthrough: [{ slot: '00:02.0', name: 'GPU iGPU' }] }));
    const igpu = modal.querySelector('.vm-pci-check[data-slot="00:02.0"]');
    expect(igpu.checked).toBe(true);
    expect(igpu.disabled).toBe(false);
    igpu.checked = false;
    igpu.onchange();
    await modal.querySelector('#vm-edit-submit').onclick();
    expect(api.put.mock.calls[0][1].pci_passthrough).toEqual([]);
  });

  it('explains when IOMMU or /dev/vfio is unavailable', async () => {
    let modal = await openEdit(baseVm(), { iommu_enabled: false, groups: [] });
    expect(modal.querySelector('#vm-edit-pci-list').textContent).toContain('IOMMU is not enabled');

    document.getElementById('modal-vm-edit')?.remove();
    modal = await openEdit(baseVm(), { ...GROUPS, vfio_available: false });
    expect(modal.querySelector('#vm-edit-pci-list .vm-pci-note.warn').textContent).toContain('/dev/vfio');
  });
});
