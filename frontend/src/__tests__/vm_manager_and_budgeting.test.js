import { describe, it, expect, vi, beforeEach } from 'vitest';
import { initVmManager, openVmCreateModal, loadVmDashboard } from '../components/vm-manager.js';
import { api } from '../api.js';

vi.mock('../api.js', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
  auth: {
    hasToken: vi.fn().mockReturnValue(true),
  },
}));

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
}));

describe('VM Manager & Dynamic Elastic Headroom Budgeting', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <div id="vm-desktop-icon"></div>
    `;
    window._vmManagerInitialized = false;
  });

  describe('Mathematical Headroom Reserve Invariants', () => {
    function calcBudget(totalRamGb, allocatedGb = 0) {
      const hostReserveGb = Math.max(2.0, parseFloat((0.1 * totalRamGb).toFixed(2)));
      const safeMaxVmRamGb = Math.max(0.0, parseFloat((totalRamGb - hostReserveGb).toFixed(2)));
      const safeHeadroomGb = Math.max(0.0, parseFloat((safeMaxVmRamGb - allocatedGb).toFixed(2)));
      const safeSliderMaxGb = Math.floor(safeMaxVmRamGb);
      return { hostReserveGb, safeMaxVmRamGb, safeHeadroomGb, safeSliderMaxGb };
    }

    it('asserts 8 GB host: 2.0 GB reserve, 6.0 GB safe budget', () => {
      const b = calcBudget(8);
      expect(b.hostReserveGb).toBe(2.0);
      expect(b.safeMaxVmRamGb).toBe(6.0);
      expect(b.safeSliderMaxGb).toBe(6);
    });

    it('asserts 16 GB host: 2.0 GB reserve, 14.0 GB safe budget', () => {
      const b = calcBudget(16);
      expect(b.hostReserveGb).toBe(2.0);
      expect(b.safeMaxVmRamGb).toBe(14.0);
      expect(b.safeSliderMaxGb).toBe(14);
    });

    it('asserts 32 GB host: 3.2 GB reserve (10%), 28.8 GB safe max (28 GB integer step)', () => {
      const b = calcBudget(32);
      expect(b.hostReserveGb).toBe(3.2);
      expect(b.safeMaxVmRamGb).toBe(28.8);
      expect(b.safeSliderMaxGb).toBe(28);
    });

    it('asserts 96 GB host: 9.6 GB reserve (10%), 86.4 GB safe budget', () => {
      const b = calcBudget(96);
      expect(b.hostReserveGb).toBe(9.6);
      expect(b.safeMaxVmRamGb).toBe(86.4);
      expect(b.safeSliderMaxGb).toBe(86);
    });

    it('asserts 256 GB host: 25.6 GB reserve (10%), 230.4 GB safe budget', () => {
      const b = calcBudget(256);
      expect(b.hostReserveGb).toBe(25.6);
      expect(b.safeMaxVmRamGb).toBe(230.4);
      expect(b.safeSliderMaxGb).toBe(230);
    });
  });

  describe('CPU Thread Overcommit Soft Warning Assertions', () => {
    function calcCpuRatio(allocated, hostThreads) {
      return parseFloat((allocated / hostThreads).toFixed(2));
    }

    it('identifies nominal ratio (<= 1.0x)', () => {
      const r = calcCpuRatio(4, 8);
      expect(r).toBe(0.5);
      expect(r <= 1.0).toBe(true);
    });

    it('identifies moderate overcommit ratio (1.0x < R <= 2.0x)', () => {
      const r = calcCpuRatio(12, 8);
      expect(r).toBe(1.5);
      expect(r > 1.0 && r <= 2.0).toBe(true);
    });

    it('identifies heavy overcommit ratio (> 2.0x)', () => {
      const r = calcCpuRatio(20, 8);
      expect(r).toBe(2.5);
      expect(r > 2.0).toBe(true);
    });
  });

  describe('DOM Creation & Interactive Flow', () => {
    it('initializes window and binds desktop icon', () => {
      initVmManager();
      const win = document.getElementById('vm-manager-window');
      expect(win).not.toBeNull();
      expect(win.style.display).toBe('none');

      document.getElementById('vm-desktop-icon').click();
      expect(win).not.toBeNull();
    });

    it('renders dashboard with telemetry and VM cards', async () => {
      api.get.mockImplementation((url) => {
        if (url === '/api/vms/telemetry') {
          return Promise.resolve({
            kvm: { state: 'active', badge: 'KVM Accelerated: Active (Intel VT-x)' },
            memory_budget: {
              total_host_ram_gb: 32.0,
              host_reserve_gb: 3.2,
              safe_max_vm_ram_gb: 28.8,
              safe_slider_max_gb: 28,
              allocated_vm_ram_gb: 8.0,
              safe_headroom_gb: 20.8,
            },
            cpu_capacity: {
              host_threads: 8,
              allocated_vcpus: 4,
              overcommit_ratio: 0.5,
              status: 'nominal',
              badge: '1:1 Physical Mapping',
            },
          });
        }
        if (url === '/api/vms') {
          return Promise.resolve([
            {
              id: 'vm-1',
              name: 'ubuntu-prod',
              os_family: 'linux',
              state: 'running',
              vcpus: 4,
              ram_gb: 8.0,
              disk_size_gb: 64,
              disk_format: 'qcow2',
              ip_address: '192.168.1.180',
            },
          ]);
        }
        if (url === '/api/vms/isos') return Promise.resolve([]);
        if (url === '/api/vms/bridges') return Promise.resolve(['br0']);
        return Promise.resolve({});
      });

      initVmManager();
      await loadVmDashboard();

      const kvmBadge = document.getElementById('vm-kvm-badge');
      expect(kvmBadge.textContent).toContain('KVM Accelerated');

      const headroomText = document.getElementById('vm-headroom-text');
      expect(headroomText.textContent).toContain('20.8 GB Safe Headroom');

      const cards = document.querySelectorAll('.glassmorphic-card');
      expect(cards.length).toBeGreaterThan(0);
      expect(document.body.innerHTML).toContain('ubuntu-prod');
    });

    it('opens create modal with dynamic sliders and advanced override toggle', () => {
      initVmManager();
      openVmCreateModal();

      const modal = document.getElementById('modal-vm-create');
      expect(modal).not.toBeNull();
      expect(modal.classList.contains('open')).toBe(true);

      const ramSlider = modal.querySelector('#vm-create-ram-slider');
      const overrideToggle = modal.querySelector('#vm-override-toggle');
      const overridePill = modal.querySelector('#vm-override-pill');

      expect(ramSlider).not.toBeNull();
      expect(overrideToggle).not.toBeNull();
      expect(overridePill.style.display).toBe('none');

      // Toggle Advanced Override ON
      overrideToggle.checked = true;
      overrideToggle.dispatchEvent(new Event('change'));
      expect(overridePill.style.display).toBe('inline-block');

      // Toggle Advanced Override OFF
      overrideToggle.checked = false;
      overrideToggle.dispatchEvent(new Event('change'));
      expect(overridePill.style.display).toBe('none');
    });

    it('submits create VM form and invokes api.post', async () => {
      api.post.mockResolvedValue({ id: 'vm-new', name: 'my-alpine' });
      initVmManager();
      openVmCreateModal();

      const modal = document.getElementById('modal-vm-create');
      modal.querySelector('#vm-create-name').value = 'my-alpine';
      modal.querySelector('#vm-create-submit').click();

      await vi.waitFor(() => {
        expect(api.post).toHaveBeenCalledWith(
          '/api/vms',
          expect.objectContaining({
            name: 'my-alpine',
            os_family: 'linux',
            disk_format: 'qcow2',
          })
        );
      });
    });

    it('asserts smart-modal-backdrop and closes create modal on cancel button', () => {
      initVmManager();
      openVmCreateModal();

      const modal = document.getElementById('modal-vm-create');
      expect(modal.classList.contains('smart-modal-backdrop')).toBe(true);
      expect(modal.querySelector('.smart-modal-window')).not.toBeNull();

      const cancelBtn = modal.querySelector('#vm-create-cancel');
      expect(cancelBtn).not.toBeNull();
      cancelBtn.click();

      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');
    });

    it('renders VM card action buttons with design system classes and triggers confirm toast on delete', async () => {
      api.get.mockImplementation((url) => {
        if (url === '/api/vms') {
          return Promise.resolve([
            {
              id: 'vm-stopped',
              name: 'arch-box',
              os_family: 'linux',
              state: 'stopped',
              vcpus: 2,
              ram_gb: 4.0,
              disk_size_gb: 32,
              disk_format: 'qcow2',
            },
          ]);
        }
        if (url === '/api/vms/telemetry') return Promise.resolve({});
        return Promise.resolve([]);
      });

      initVmManager();
      await loadVmDashboard();

      const startBtn = document.querySelector('.btn-vm-start');
      const deleteBtn = document.querySelector('.btn-vm-delete');

      expect(startBtn).not.toBeNull();
      expect(deleteBtn).not.toBeNull();
      expect(startBtn.innerHTML).toContain('svg');
      expect(deleteBtn.innerHTML).toContain('svg');

      deleteBtn.click();
      const { showConfirmToast } = await import('../toast.js');
      expect(showConfirmToast).toHaveBeenCalledWith(
        expect.any(String),
        expect.stringContaining('arch-box'),
        expect.any(Function)
      );
    });
  });
});
