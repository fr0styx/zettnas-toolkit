import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  initVmManager,
  openVmCreateModal,
  loadVmDashboard,
  copyToClipboard,
  openVmConsole,
  setConsoleFocus,
  openIsoManagerModal,
  OFFICIAL_ISO_CATALOG
} from '../components/vm-manager.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';

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

    it('asserts universal copyToClipboard works in secure context and falls back in non-secure HTTP', async () => {
      // 1. Secure context with navigator.clipboard
      window.isSecureContext = true;
      Object.assign(navigator, {
        clipboard: {
          writeText: vi.fn().mockResolvedValue(undefined),
        },
      });

      const okSecure = await copyToClipboard('192.168.1.180');
      expect(okSecure).toBe(true);
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith('192.168.1.180');

      // 2. Non-secure context fallback using document.execCommand
      window.isSecureContext = false;
      document.execCommand = vi.fn().mockReturnValue(true);

      const okFallback = await copyToClipboard('ssh root@192.168.1.180');
      expect(okFallback).toBe(true);
      expect(document.execCommand).toHaveBeenCalledWith('copy');
    });

    it('mounts interactive #vm-console-window with DockManager registration, controls, and canvas', () => {
      window.DockManager = {
        windows: {},
        register: vi.fn(),
        restore: vi.fn(),
        minimize: vi.fn(),
        closeWindow: vi.fn(),
      };

      openVmConsole('vm-test-1', 'ubuntu-node');

      const consoleWin = document.getElementById('vm-console-window');
      expect(consoleWin).not.toBeNull();
      expect(consoleWin.classList.contains('vm-console-window')).toBe(true);

      // Verify DockManager registration
      expect(window.DockManager.register).toHaveBeenCalledWith(
        'vm-console',
        consoleWin,
        '#i-vm',
        'Console: ubuntu-node'
      );

      // Verify toolbar controls
      expect(consoleWin.querySelector('#btn-console-mode-gui')).not.toBeNull();
      expect(consoleWin.querySelector('#btn-console-mode-cli')).not.toBeNull();
      expect(consoleWin.querySelector('#vm-console-resolution-stat')).not.toBeNull();
      expect(consoleWin.querySelector('#vm-console-adapter-stat')).not.toBeNull();
      expect(consoleWin.querySelector('#btn-vnc-cad')).not.toBeNull();
      expect(consoleWin.querySelector('#btn-vnc-keys')).not.toBeNull();
      expect(consoleWin.querySelector('#btn-vnc-fullscreen')).not.toBeNull();
      expect(consoleWin.querySelector('#btn-vnc-reconnect')).not.toBeNull();
      expect(consoleWin.querySelector('#btn-vnc-clipboard')).not.toBeNull();

      // Verify canvas terminal viewport
      const canvas = consoleWin.querySelector('#vm-console-canvas');
      expect(canvas).not.toBeNull();
    });

    it('renders Join VM popover on VM cards with multi-protocol GUI & connection options', async () => {
      api.get.mockImplementation((url) => {
        if (url === '/api/vms') {
          return Promise.resolve([
            {
              id: 'vm-online',
              name: 'web-prod',
              os_family: 'linux',
              state: 'running',
              vcpus: 4,
              ram_gb: 8.0,
              disk_size_gb: 64,
              disk_format: 'qcow2',
              ip_address: '192.168.1.200',
            },
          ]);
        }
        if (url === '/api/vms/telemetry') return Promise.resolve({});
        return Promise.resolve([]);
      });

      initVmManager();
      await loadVmDashboard();

      // Check prominent KVM GUI button directly on VM card
      const guiBtn = document.querySelector('.btn-vm-gui');
      const consoleBtn = document.querySelector('.btn-vm-console');
      expect(guiBtn).not.toBeNull();
      expect(consoleBtn).not.toBeNull();
      expect(guiBtn.textContent).toContain('KVM GUI');

      const joinToggle = document.querySelector('.btn-vm-join-toggle');
      expect(joinToggle).not.toBeNull();

      const popover = document.getElementById('vm-join-popover-vm-online');
      expect(popover).not.toBeNull();
      expect(popover.style.display).toBe('none');

      // Click to toggle open
      joinToggle.click();
      expect(popover.style.display).toBe('flex');

      // Check items inside popover
      expect(popover.querySelector('.btn-join-gui')).not.toBeNull();
      expect(popover.querySelector('.btn-join-console')).not.toBeNull();
      expect(popover.querySelector('.btn-join-web')).not.toBeNull();
      expect(popover.querySelector('.btn-join-vnc')).not.toBeNull();
      expect(popover.querySelector('.btn-join-rdp')).not.toBeNull();
      expect(popover.querySelector('.btn-join-ssh')).not.toBeNull();
      expect(popover.querySelector('.btn-join-ip')).not.toBeNull();

      // Click Join Web Console
      popover.querySelector('.btn-join-console').click();
      expect(document.getElementById('vm-console-window')).not.toBeNull();
    });

    it('toggles Display Mode between KVM GUI and Serial TTY in console window', () => {
      openVmConsole('vm-mode-test', 'gui-test-vm', 'gui');

      const consoleWin = document.getElementById('vm-console-window');
      expect(consoleWin).not.toBeNull();

      const btnGui = consoleWin.querySelector('#btn-console-mode-gui');
      const btnCli = consoleWin.querySelector('#btn-console-mode-cli');
      const resStat = consoleWin.querySelector('#vm-console-resolution-stat');
      const adpStat = consoleWin.querySelector('#vm-console-adapter-stat');
      const titleTxt = consoleWin.querySelector('#vm-console-title-text');

      expect(btnGui.classList.contains('active')).toBe(true);
      expect(btnCli.classList.contains('active')).toBe(false);
      expect(resStat.textContent).toBe('1920 × 1080');
      expect(adpStat.textContent).toBe('VirtIO-GPU');
      expect(titleTxt.textContent).toContain('KVM GUI');

      // Switch to Serial TTY
      btnCli.click();
      expect(btnCli.classList.contains('active')).toBe(true);
      expect(btnGui.classList.contains('active')).toBe(false);
      expect(resStat.textContent).toBe('80 × 25 TTY');
      expect(adpStat.textContent).toBe('Serial TTY');
      expect(titleTxt.textContent).toContain('Serial TTY');

      // Switch back to KVM GUI
      btnGui.click();
      expect(btnGui.classList.contains('active')).toBe(true);
      expect(btnCli.classList.contains('active')).toBe(false);
      expect(resStat.textContent).toBe('1920 × 1080');
      expect(adpStat.textContent).toBe('VirtIO-GPU');
      expect(titleTxt.textContent).toContain('KVM GUI');
    });

    it('supports host folder passthrough (VirtIO-FS / 9p) and secondary disks in create modal', async () => {
      api.post.mockResolvedValue({ id: 'vm-shares', name: 'appdata-vm' });
      initVmManager();
      openVmCreateModal();

      const modal = document.getElementById('modal-vm-create');
      expect(modal).not.toBeNull();

      // Add Host Folder Share
      const btnAddShare = modal.querySelector('#btn-add-host-share');
      expect(btnAddShare).not.toBeNull();
      btnAddShare.click();

      const shareRow = modal.querySelector('.host-share-row');
      expect(shareRow).not.toBeNull();
      shareRow.querySelector('.share-host-path').value = '/mnt/user/appdata';
      shareRow.querySelector('.share-mount-tag').value = 'appdata_mount';

      // Add Secondary Virtual Disk
      const btnAddDisk = modal.querySelector('#btn-add-secondary-disk');
      expect(btnAddDisk).not.toBeNull();
      btnAddDisk.click();

      const diskRow = modal.querySelector('.secondary-disk-row');
      expect(diskRow).not.toBeNull();
      diskRow.querySelector('.disk-name').value = 'secondary-data';
      diskRow.querySelector('.disk-size').value = '100';

      // Submit
      modal.querySelector('#vm-create-name').value = 'appdata-vm';
      modal.querySelector('#vm-create-submit').click();

      await vi.waitFor(() => {
        expect(api.post).toHaveBeenCalledWith(
          '/api/vms',
          expect.objectContaining({
            name: 'appdata-vm',
            host_shares: expect.arrayContaining([
              expect.objectContaining({
                host_path: '/mnt/user/appdata',
                mount_tag: 'appdata_mount',
              }),
            ]),
            secondary_disks: expect.arrayContaining([
              expect.objectContaining({
                name: 'secondary-data',
                size_gb: 100,
              }),
            ]),
          })
        );
      });
    });

    it('mounts ISO Manager Modal as an os-window with Official OS Catalog and Local Storage upload', () => {
      openIsoManagerModal('catalog');

      const modal = document.getElementById('modal-iso-manager');
      expect(modal).not.toBeNull();
      expect(modal.classList.contains('os-window')).toBe(true);
      expect(modal.classList.contains('vm-iso-window')).toBe(true);

      // Verify window controls
      expect(modal.querySelector('#iso-win-min')).not.toBeNull();
      expect(modal.querySelector('#iso-win-max')).not.toBeNull();
      expect(modal.querySelector('#iso-modal-close')).not.toBeNull();

      // Verify official catalog items
      expect(OFFICIAL_ISO_CATALOG.length).toBeGreaterThanOrEqual(5);
      expect(OFFICIAL_ISO_CATALOG.some((c) => c.name.includes('Ubuntu'))).toBe(true);
      expect(OFFICIAL_ISO_CATALOG.some((c) => c.name.includes('VirtIO Windows'))).toBe(true);

      // Verify 1-click download button exists
      const dlBtn = modal.querySelector('.btn-dl-catalog');
      expect(dlBtn).not.toBeNull();

      // Switch to Local Storage Upload Tab
      const tabLocalBtn = modal.querySelector('#tab-btn-local');
      expect(tabLocalBtn).not.toBeNull();
      tabLocalBtn.click();

      expect(modal.querySelector('#tab-content-local').style.display).toBe('block');
      expect(modal.querySelector('#tab-content-catalog').style.display).toBe('none');

      const dropzone = modal.querySelector('#iso-dropzone');
      expect(dropzone).not.toBeNull();
      expect(dropzone.innerHTML).toContain('/mnt/user/isos');
    });

    it('captures keyboard events exclusively in VM console and manages focus state', () => {
      openVmConsole('vm-test-capture', 'Test Captured VM');

      const consoleWin = document.getElementById('vm-console-window');
      expect(consoleWin).not.toBeNull();
      expect(consoleWin.dataset.focused).toBe('true');

      const pill = consoleWin.querySelector('#vm-console-kbd-pill');
      expect(pill).not.toBeNull();
      expect(pill.textContent).toContain('Captured');

      // Toggling focus to false updates dataset and pill
      setConsoleFocus(false);
      expect(consoleWin.dataset.focused).toBe('false');
      expect(pill.textContent).toContain('Click to capture');

      // Toggling focus to true restores capture state
      setConsoleFocus(true);
      expect(consoleWin.dataset.focused).toBe('true');
      expect(pill.textContent).toContain('Captured');

      // Test keydown on canvas stops propagation and does not eat 't'
      const canvas = document.getElementById('vm-console-canvas');
      expect(canvas).not.toBeNull();

      const keyEvent = new KeyboardEvent('keydown', { key: 't', bubbles: true, cancelable: true });
      const stopPropSpy = vi.spyOn(keyEvent, 'stopPropagation');
      canvas.dispatchEvent(keyEvent);
      expect(stopPropSpy).toHaveBeenCalled();

      // Test typing full 'root' sequence via canvas.onkeydown
      ['r', 'o', 'o', 't'].forEach((k) => {
        const ev = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true });
        canvas.dispatchEvent(ev);
      });

      // Test minimize button unsets focused state
      const minBtn = document.getElementById('vm-console-min');
      expect(minBtn).not.toBeNull();
      minBtn.click();
      expect(consoleWin.style.display).toBe('none');
      expect(consoleWin.dataset.focused).toBe('false');

      // Test close button hides window and removes focus
      const closeBtn = document.getElementById('vm-console-close');
      expect(closeBtn).not.toBeNull();
      closeBtn.click();
      expect(consoleWin.style.display).toBe('none');
      expect(consoleWin.classList.contains('window-minimized')).toBe(true);
      expect(consoleWin.dataset.focused).toBe('false');
    });

    it('executes guest CLI commands and recalls history without triggering toast notifications', () => {
      openVmConsole('vm-test-cli', 'Test Guest VM', 'cli');

      const consoleWin = document.getElementById('vm-console-window');
      expect(consoleWin).not.toBeNull();
      const canvas = document.getElementById('vm-console-canvas');
      expect(canvas).not.toBeNull();

      // Type 'ls' and press Enter
      ['l', 's'].forEach((k) => {
        canvas.onkeydown(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));
      });
      canvas.onkeydown(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));

      // Type 'uname -a' and press Enter
      'uname -a'.split('').forEach((k) => {
        canvas.onkeydown(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));
      });
      canvas.onkeydown(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));

      // Press ArrowUp to recall last command ('uname -a')
      const upEvt = new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true, cancelable: true });
      canvas.onkeydown(upEvt);

      // Press ArrowDown to clear recalled command
      const downEvt = new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true });
      canvas.onkeydown(downEvt);

      // Verify no toast was ever called for console input
      expect(showToast).not.toHaveBeenCalledWith(expect.stringContaining('Guest executed'));

      // Switch to GUI mode and press Enter - verify no toast
      const btnGui = consoleWin.querySelector('#btn-console-mode-gui');
      btnGui.click();
      canvas.onkeydown(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
      expect(showToast).not.toHaveBeenCalledWith(expect.stringContaining('Guest executed'));
    });
  });
});

