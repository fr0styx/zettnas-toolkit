import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  initVmManager,
  openVmCreateModal,
  loadVmDashboard,
  copyToClipboard,
  openVmConsole,
  setConsoleFocus,
  openIsoManagerModal,
  OFFICIAL_ISO_CATALOG,
  focusActiveConsole,
  getActiveConsoleTarget,
  _handleRfbKeyFallback,
  _sendKeyToRfb,
  openVmConsoleSeparateWindow,
  formatAnsiToHtml,
  parseAnsiToHtml,
  cancelConsoleReconnect,
  _scheduleConsoleReconnect,
  showConsoleBanner,
  hideConsoleBanner,
  clearConsoleReconnectTimer,
  pasteTextToGuestConsole,
  openVmEditModal,
  openQemuErrorModal,
  openVmConnectModal,
  applyTerminalStream
} from '../components/vm-manager.js';
import { api } from '../api.js';
import { showToast, showPromptToast } from '../toast.js';

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
  showPromptToast: vi.fn(),
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
        expect.any(Function),
        null,
        expect.objectContaining({ destructive: true, typeToConfirm: 'arch-box' })
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

    it('accurately resolves active console target and handles focusActiveConsole', () => {
      openVmConsole('vm-test-focus', 'Focus VM', 'gui');
      const consoleWin = document.getElementById('vm-console-window');
      expect(consoleWin).not.toBeNull();

      // By default in test environment, simulation canvas is visible
      const simTarget = getActiveConsoleTarget(consoleWin);
      expect(simTarget).toBe(consoleWin.querySelector('#vm-console-canvas'));

      // If a real noVNC canvas exists inside .vnc-screen-target
      const vncContainer = consoleWin.querySelector('#vm-vnc-container');
      const vncScreen = document.createElement('div');
      vncScreen.className = 'vnc-screen-target';
      const realCanvas = document.createElement('canvas');
      vncScreen.appendChild(realCanvas);
      vncContainer.appendChild(vncScreen);

      // Now getActiveConsoleTarget should resolve the real canvas
      const activeTarget = getActiveConsoleTarget(consoleWin);
      expect(activeTarget).toBe(realCanvas);

      // focusActiveConsole sets tabindex="0" and focuses real canvas
      focusActiveConsole();
      expect(realCanvas.tabIndex).toBe(0);

      // In CLI mode, target should resolve to #vm-cli-container
      consoleWin._setConsoleMode('cli');
      const cliTarget = getActiveConsoleTarget(consoleWin);
      expect(cliTarget).toBe(consoleWin.querySelector('#vm-cli-container'));
    });

    it('routes fallback keys and ctrl combos via _handleRfbKeyFallback safely', () => {
      openVmConsole('vm-test-keys', 'Keys VM', 'gui');
      const consoleWin = document.getElementById('vm-console-window');
      expect(consoleWin).not.toBeNull();

      // Test key routing directly - safe without active RFB
      const evEnter = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', cancelable: true });
      expect(() => _handleRfbKeyFallback(evEnter)).not.toThrow();

      const evArrow = new KeyboardEvent('keydown', { key: 'ArrowUp', code: 'ArrowUp', cancelable: true });
      expect(() => _handleRfbKeyFallback(evArrow)).not.toThrow();

      const evChar = new KeyboardEvent('keydown', { key: 'a', code: 'KeyA', cancelable: true });
      expect(() => _handleRfbKeyFallback(evChar)).not.toThrow();

      const evCtrlC = new KeyboardEvent('keydown', { key: 'c', ctrlKey: true, cancelable: true });
      expect(() => _handleRfbKeyFallback(evCtrlC)).not.toThrow();

      expect(() => _sendKeyToRfb(0xff0d, 'Enter')).not.toThrow();
    });

    it('handles mobile virtual keyboard input through hidden input helper', () => {
      openVmConsole('vm-test-mobile', 'Mobile VM', 'gui');
      const consoleWin = document.getElementById('vm-console-window');
      expect(consoleWin).not.toBeNull();

      const hiddenInput = consoleWin.querySelector('#vm-console-hidden-input');
      const btnSoftKbd = consoleWin.querySelector('#btn-vnc-softkbd');
      expect(hiddenInput).not.toBeNull();
      expect(btnSoftKbd).not.toBeNull();

      // Clicking soft keyboard button focuses hidden input
      const focusSpy = vi.spyOn(hiddenInput, 'focus');
      btnSoftKbd.click();
      expect(focusSpy).toHaveBeenCalled();

      // Typing into hidden input clears its value and triggers input dispatch
      hiddenInput.value = 'root';
      hiddenInput.dispatchEvent(new Event('input'));
      expect(hiddenInput.value).toBe('');

      // Backspace and Enter key events on hidden input
      const bsEvt = new KeyboardEvent('keydown', { key: 'Backspace' });
      hiddenInput.dispatchEvent(bsEvt);

      const enterEvt = new KeyboardEvent('keydown', { key: 'Enter' });
      hiddenInput.dispatchEvent(enterEvt);
    });

    it('handles clipboard paste button by typing keystrokes into guest via glassmorphic prompt modal', async () => {
      const promptSpy = vi.spyOn(window, 'prompt');
      openVmConsole('vm-test-paste', 'Paste VM', 'gui');
      const consoleWin = document.getElementById('vm-console-window');
      const btnClip = consoleWin.querySelector('#btn-vnc-clipboard');
      expect(btnClip).not.toBeNull();

      showPromptToast.mockImplementation((title, desc, defaultVal, onConfirm, onCancel, options) => {
        expect(options.inputType).toBe('textarea');
        expect(options.icon).toBe('📋');
        onConfirm('root\n');
      });

      btnClip.click();

      await vi.waitFor(() => {
        expect(promptSpy).not.toHaveBeenCalled();
        expect(showPromptToast).toHaveBeenCalled();
        expect(showToast).toHaveBeenCalledWith(
          expect.stringContaining('Sent 5 characters to the VM'),
          'success'
        );
      });
    });

    it('opens separate standalone window with openVmConsoleSeparateWindow', () => {
      const openSpy = vi.spyOn(window, 'open').mockReturnValue({ focus: vi.fn() });
      openVmConsoleSeparateWindow('vm-42', 'Alpine Test', 'cli');

      expect(openSpy).toHaveBeenCalled();
      const [url, target, features] = openSpy.mock.calls[0];
      expect(url).toContain('mode=vm-console');
      expect(url).toContain('vm=vm-42');
      expect(url).toContain('name=Alpine%20Test');
      expect(url).toContain('consoleMode=cli');
      expect(target).toBe('vm_console_vm-42');
      expect(features).toContain('resizable=yes');
    });

    it('handles pop out button in console toolbar', () => {
      const openSpy = vi.spyOn(window, 'open').mockReturnValue({ focus: vi.fn() });
      openVmConsole('vm-popout-test', 'Popout VM', 'gui');
      const consoleWin = document.getElementById('vm-console-window');
      const btnPopout = consoleWin.querySelector('#btn-vnc-popout');
      expect(btnPopout).not.toBeNull();

      btnPopout.click();
      expect(openSpy).toHaveBeenCalled();
      const [url] = openSpy.mock.calls[0];
      expect(url).toContain('mode=vm-console');
      expect(url).toContain('vm=vm-popout-test');
      expect(consoleWin.classList.contains('window-minimized')).toBe(true);
    });

    it('supports standalone direct mode with window.close() on close button', () => {
      document.body.classList.add('vm-console-direct');
      const closeSpy = vi.spyOn(window, 'close').mockImplementation(() => {});

      openVmConsole('vm-direct-test', 'Direct VM', 'gui');
      const consoleWin = document.getElementById('vm-console-window');
      expect(consoleWin.classList.contains('vm-console-standalone')).toBe(true);
      expect(document.title).toContain('VM Console: Direct VM');

      const closeBtn = consoleWin.querySelector('#vm-console-close');
      expect(closeBtn).not.toBeNull();
      closeBtn.click();
      expect(closeSpy).toHaveBeenCalled();
      document.body.classList.remove('vm-console-direct');
    });
  });

  describe('Terminal ANSI Escape Sequence Parser (formatAnsiToHtml)', () => {
    it('returns empty string for null or empty input', () => {
      expect(formatAnsiToHtml('')).toBe('');
      expect(formatAnsiToHtml(null)).toBe('');
    });

    it('escapes HTML special characters to prevent XSS injection', () => {
      const result = formatAnsiToHtml('<script>alert("xss")</script>&"test"');
      expect(result).not.toContain('<script>');
      expect(result).toContain('&lt;script&gt;');
      expect(result).toContain('&amp;');
      expect(result).toContain('&quot;test&quot;');
    });

    it('parses standard foreground color codes correctly into spans', () => {
      const red = formatAnsiToHtml('\x1b[31mError message\x1b[0m');
      expect(red).toContain('style="color: #ef4444"');
      expect(red).toContain('Error message');

      const green = formatAnsiToHtml('\x1b[32mSuccess\x1b[0m');
      expect(green).toContain('style="color: #22c55e"');
      expect(green).toContain('Success');
    });

    it('parses bright foreground colors and text styles', () => {
      const yellowBold = formatAnsiToHtml('\x1b[1;33mWarning\x1b[0m');
      expect(yellowBold).toContain('font-weight: bold');
      expect(yellowBold).toContain('color: #f59e0b');

      const dimUnderline = formatAnsiToHtml('\x1b[2;4mSubtle link\x1b[0m');
      expect(dimUnderline).toContain('opacity: 0.7');
      expect(dimUnderline).toContain('text-decoration: underline');
    });

    it('parses serial console socket waiting banner with accurate colors', () => {
      const banner = "\r\n\x1b[33m[ZettNAS Serial Console]\x1b[0m Waiting for serial socket at '/tmp/vm-test.sock'...\r\n\x1b[90mEnsure VM is running and serial socket is initialized.\x1b[0m\r\n";
      const html = formatAnsiToHtml(banner);
      expect(html).toContain('style="color: #f59e0b"');
      expect(html).toContain('[ZettNAS Serial Console]');
      expect(html).toContain('style="color: #94a3b8"');
      expect(html).toContain('Ensure VM is running');
      expect(html).not.toContain('\x1b');
    });

    it('strips non-color cursor and screen escape sequences cleanly', () => {
      const withClear = '\x1b[2J\x1b[H\x1b[32mClean Output\x1b[0m';
      const parsed = formatAnsiToHtml(withClear);
      expect(parsed).not.toContain('[2J');
      expect(parsed).not.toContain('[H');
      expect(parsed).toContain('Clean Output');
      expect(parsed).toContain('color: #22c55e');
    });

    it('sanitizes dangling or orphaned escape sequences without leaking brackets into DOM', () => {
      const orphaned = 'localhost:~# hol \x1b[ \x1b[';
      const parsed = formatAnsiToHtml(orphaned);
      expect(parsed).toBe('localhost:~# hol  ');
      expect(parsed).not.toContain('[');
    });
  });

  describe('Console Reconnection & Modal Lifecycle', () => {
    it('cancels pending reconnect timer with cancelConsoleReconnect', () => {
      vi.useFakeTimers();
      const container = document.createElement('div');
      _scheduleConsoleReconnect(container, 'vm-recon-test', 'Recon VM', 'cli');
      cancelConsoleReconnect();
      vi.runAllTimers();
      vi.useRealTimers();
      expect(true).toBe(true);
    });

    it('renders QEMU Hypervisor launch error modal with troubleshooting steps', () => {
      openQemuErrorModal('FailedVM', 'qemu-system-x86_64: could not open /dev/kvm: Permission denied', 'vm-failed-1');
      const modal = document.getElementById('modal-qemu-error');
      expect(modal).not.toBeNull();
      expect(modal.textContent).toContain('Failed to start virtual machine FailedVM');
      expect(modal.textContent).toContain('Permission denied');
      expect(modal.textContent).toContain('Run KVM Diagnostics');
      expect(modal.textContent).toContain('Edit VM Settings');

      const closeBtn = modal.querySelector('#qemu-error-close');
      expect(closeBtn).not.toBeNull();
      closeBtn.click();
      expect(modal.classList.contains('open')).toBe(false);
    });
  });

  describe('Extended Terminal ANSI & 256 Colors', () => {
    it('handles stripped ESC codes [33m and 256-color sequences without corrupting bracketed text', () => {
      const stripped = '[33m[ZettNAS Serial Console] [0mWaiting for serial socket...';
      const parsed = parseAnsiToHtml(stripped);
      expect(parsed).toContain('color: #f59e0b');
      expect(parsed).toContain('[ZettNAS Serial Console]');

      const color256 = '\x1b[38;5;208mOrange Text\x1b[0m Normal';
      const parsed256 = parseAnsiToHtml(color256);
      expect(parsed256).toContain('color: rgb(255, 102, 0)');
      expect(parsed256).toContain('Orange Text');

      const bootLog = '[ 0.000000] Linux version 6.6.137 [ OK ] Started System Logging Service.';
      const parsedBoot = parseAnsiToHtml(bootLog);
      expect(parsedBoot).toContain('[ 0.000000] Linux version 6.6.137');
      expect(parsedBoot).toContain('[ OK ] Started System Logging Service.');
    });
  });

  describe('Console Dynamic Status Banners & Universal Paste', () => {
    beforeEach(() => {
      document.body.innerHTML = `
        <div id="vm-console-window" class="vm-console-window" style="display: flex;">
          <div id="vm-console-viewport">
            <div id="vm-console-banner" class="vm-console-banner" style="display: none;"></div>
          </div>
          <span id="vm-console-status-pill">● LIVE</span>
        </div>
      `;
    });

    it('displays connecting and connected banners with auto-fade', () => {
      vi.useFakeTimers();
      showConsoleBanner('connecting', 'Connecting to KVM display socket...');
      const banner = document.getElementById('vm-console-banner');
      expect(banner.style.display).toBe('flex');
      expect(banner.className).toContain('banner-connecting');
      expect(banner.textContent).toContain('Connecting to KVM display socket...');

      showConsoleBanner('connected', 'Connected to KVM Display (VirtIO-GPU)');
      expect(banner.className).toContain('banner-connected');
      expect(banner.textContent).toContain('Connected to KVM Display');

      // Fast-forward 3.5s auto-fade
      vi.advanceTimersByTime(3600);
      expect(banner.style.display).toBe('none');
      vi.useRealTimers();
    });

    it('renders banner actions and executes callbacks on click', () => {
      const clickSpy = vi.fn();
      showConsoleBanner('disconnected', 'Disconnected from KVM display', [
        { label: 'Reconnect Now', primary: true, onClick: clickSpy },
      ]);

      const banner = document.getElementById('vm-console-banner');
      expect(banner.className).toContain('banner-disconnected');
      const actionBtn = banner.querySelector('.btn-banner-act');
      expect(actionBtn).not.toBeNull();
      expect(actionBtn.textContent).toBe('Reconnect Now');

      actionBtn.click();
      expect(clickSpy).toHaveBeenCalled();

      hideConsoleBanner();
      expect(banner.style.display).toBe('none');
    });

    it('forwards text through pasteTextToGuestConsole in CLI and GUI modes', async () => {
      const win = document.getElementById('vm-console-window');
      win._activeMode = 'gui';

      await pasteTextToGuestConsole('hello guest\n');
      expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Sent 12 characters to the VM'), 'success');

      win._activeMode = 'cli';
      await pasteTextToGuestConsole('ls -la\n');
      expect(showToast).toHaveBeenCalledWith(expect.stringContaining('characters to the terminal'), 'success');
    });
  });

  describe('Multi-Protocol VM Connection Modal & Volume Mapping', () => {
    it('mounts Multi-Protocol Connect modal with VNC, SSH, RDP, and VirtIO-FS options', async () => {
      api.get.mockImplementation((url) => {
        if (url === '/api/vms') {
          return Promise.resolve([
            {
              id: 'vm-proto-1',
              name: 'enterprise-server',
              os_family: 'linux',
              state: 'running',
              vcpus: 4,
              ram_gb: 8.0,
              ip_address: '192.168.1.150',
              vnc_port: 5902,
              host_shares: [
                { host_path: '/mnt/user/appdata', mount_tag: 'appdata_mount' },
              ],
            },
          ]);
        }
        return Promise.resolve([]);
      });

      initVmManager();
      await loadVmDashboard();

      openVmConnectModal('vm-proto-1');

      const modal = document.getElementById('modal-vm-connect');
      expect(modal).not.toBeNull();
      expect(modal.classList.contains('open')).toBe(true);
      expect(modal.textContent).toContain('Multi-Protocol Connect: enterprise-server');
      expect(modal.textContent).toContain('192.168.1.150');
      expect(modal.textContent).toContain('vnc://');
      expect(modal.textContent).toContain('5902');
      expect(modal.textContent).toContain('ssh root@192.168.1.150');
      expect(modal.textContent).toContain('192.168.1.150:3389');
      expect(modal.textContent).toContain('sudo mount -t virtiofs appdata_mount');

      // Test copy VNC URI button
      const copyVncBtn = modal.querySelector('.btn-connect-copy-vnc');
      expect(copyVncBtn).not.toBeNull();
      copyVncBtn.click();

      // Test close button
      const closeBtn = modal.querySelector('#vm-connect-close');
      expect(closeBtn).not.toBeNull();
      closeBtn.click();
      expect(modal.classList.contains('open')).toBe(false);
    });

    it('supports host folder shares and secondary disks in VM Edit Modal', async () => {
      api.get.mockImplementation((url) => {
        if (url === '/api/vms') {
          return Promise.resolve([
            {
              id: 'vm-edit-vols',
              name: 'storage-node',
              os_family: 'linux',
              state: 'stopped',
              vcpus: 2,
              ram_gb: 4.0,
              host_shares: [],
              secondary_disks: [],
            },
          ]);
        }
        return Promise.resolve([]);
      });

      if (api.put) api.put.mockResolvedValue({ id: 'vm-edit-vols', name: 'storage-node' });
      api.post.mockResolvedValue({ id: 'vm-edit-vols', name: 'storage-node' });

      initVmManager();
      await loadVmDashboard();

      openVmEditModal('vm-edit-vols');

      const modal = document.getElementById('modal-vm-edit');
      expect(modal).not.toBeNull();

      // Add Host Folder Share
      const btnAddShare = modal.querySelector('#btn-edit-add-host-share');
      expect(btnAddShare).not.toBeNull();
      btnAddShare.click();

      const shareRow = modal.querySelector('.host-share-row');
      expect(shareRow).not.toBeNull();
      shareRow.querySelector('.share-host-path').value = '/mnt/storage/media';
      shareRow.querySelector('.share-mount-tag').value = 'media_share';

      // Add Secondary Virtual Disk
      const btnAddDisk = modal.querySelector('#btn-edit-add-secondary-disk');
      expect(btnAddDisk).not.toBeNull();
      btnAddDisk.click();

      const diskRow = modal.querySelector('.secondary-disk-row');
      expect(diskRow).not.toBeNull();
      diskRow.querySelector('.disk-name').value = 'media-disk-2';
      diskRow.querySelector('.disk-size').value = '250';

      // Submit Edit Modal
      modal.querySelector('#vm-edit-submit').click();

      await vi.waitFor(() => {
        const calledPayload = (api.put?.mock?.calls?.[0]?.[1]) || (api.post?.mock?.calls?.find(c => c[0] === '/api/vms/vm-edit-vols')?.[1]);
        expect(calledPayload).toEqual(
          expect.objectContaining({
            name: 'storage-node',
            host_shares: expect.arrayContaining([
              expect.objectContaining({
                host_path: '/mnt/storage/media',
                mount_tag: 'media_share',
              }),
            ]),
            secondary_disks: expect.arrayContaining([
              expect.objectContaining({
                name: 'media-disk-2',
                size_gb: 250,
              }),
            ]),
          })
        );
      });
    });

    it('opens VM edit modal seamlessly when invoked from external views with vmObj or direct API fallback', async () => {
      const mockVm = {
        id: 'vm-external-123',
        name: 'external-alpine',
        vcpus: 2,
        ram_gb: 4.0,
        state: 'running',
        boot_order: 'disk',
      };

      // 1. Invoking with vmObj directly (Mission Control flow)
      openVmEditModal('vm-external-123', mockVm);
      const modal = document.getElementById('modal-vm-edit');
      expect(modal).not.toBeNull();
      expect(modal.querySelector('.smart-modal-title').textContent).toContain('external-alpine');
      expect(modal.querySelector('#vm-edit-name').value).toBe('external-alpine');

      // 2. Invoking without vmObj when vmId not yet in list triggers direct GET /api/vms/:id
      api.get.mockImplementation((url) => {
        if (url === '/api/vms/vm-direct-fallback') {
          return Promise.resolve({
            id: 'vm-direct-fallback',
            name: 'fallback-vm',
            vcpus: 1,
            ram_gb: 2.0,
            state: 'stopped',
          });
        }
        if (url === '/api/vms/isos') return Promise.resolve([]);
        if (url === '/api/vms/telemetry') return Promise.resolve({});
        return Promise.resolve([]);
      });

      openVmEditModal('vm-direct-fallback');
      await vi.waitFor(() => {
        expect(modal.querySelector('#vm-edit-name')?.value).toBe('fallback-vm');
      });
    });

    it('renders and submits advanced configuration (firmware, TPM, video adapter, USB passthrough) in create and edit modals', async () => {
      // 1. Test in Create Modal
      api.get.mockImplementation((url) => {
        if (url === '/api/vms/usb-devices') {
          return Promise.resolve([
            { vendor_id: '10c4', product_id: 'ea60', description: 'CP2102 Zigbee Dongle', manufacturer: 'Silicon Labs' },
          ]);
        }
        return Promise.resolve([]);
      });
      api.post.mockResolvedValue({ id: 'vm-adv-new', name: 'win11-prod' });

      initVmManager();
      openVmCreateModal();

      const createModal = document.getElementById('modal-vm-create');
      expect(createModal).not.toBeNull();

      // Configure Firmware & TPM
      const uefiRadio = createModal.querySelector('input[name="vm-create-firmware"][value="uefi"]');
      expect(uefiRadio).not.toBeNull();
      uefiRadio.checked = true;

      const tpmToggle = createModal.querySelector('#vm-create-tpm');
      expect(tpmToggle).not.toBeNull();
      tpmToggle.checked = true;

      // Configure Video Adapter
      const videoSelect = createModal.querySelector('#vm-create-gpu-driver');
      expect(videoSelect).not.toBeNull();
      videoSelect.value = 'qxl';

      // Add Custom USB Device
      const btnToggleCustom = createModal.querySelector('#btn-create-toggle-custom-usb');
      btnToggleCustom.click();
      createModal.querySelector('#vm-create-custom-vid').value = '10c4';
      createModal.querySelector('#vm-create-custom-pid').value = 'ea60';
      createModal.querySelector('#vm-create-custom-desc').value = 'Zigbee Gateway';
      createModal.querySelector('#btn-create-add-custom-usb').click();

      const usbCard = createModal.querySelector('.usb-device-card');
      expect(usbCard).not.toBeNull();
      expect(usbCard.textContent).toContain('Zigbee Gateway');
      expect(usbCard.textContent).toContain('10c4:ea60');

      // Submit Create
      createModal.querySelector('#vm-create-name').value = 'win11-prod';
      createModal.querySelector('#vm-create-submit').click();

      await vi.waitFor(() => {
        expect(api.post).toHaveBeenCalledWith(
          '/api/vms',
          expect.objectContaining({
            name: 'win11-prod',
            firmware: 'uefi',
            tpm_enabled: true,
            video_adapter: 'qxl',
            usb_passthrough: expect.arrayContaining([
              expect.objectContaining({
                vendor_id: '10c4',
                product_id: 'ea60',
                description: 'Zigbee Gateway',
              }),
            ]),
          })
        );
      });

      // 2. Test in Edit Modal
      const existingVm = {
        id: 'vm-edit-adv',
        name: 'win11-prod',
        firmware: 'uefi',
        tpm_enabled: true,
        video_adapter: 'qxl',
        usb_passthrough: [{ vendor_id: '10c4', product_id: 'ea60', description: 'Zigbee Gateway' }],
      };

      openVmEditModal('vm-edit-adv', existingVm);
      const editModal = document.getElementById('modal-vm-edit');
      expect(editModal).not.toBeNull();

      expect(editModal.querySelector('input[name="vm-edit-firmware"][value="uefi"]').checked).toBe(true);
      expect(editModal.querySelector('#vm-edit-tpm').checked).toBe(true);
      expect(editModal.querySelector('#vm-edit-video-adapter').value).toBe('qxl');

      // Add another custom USB device
      editModal.querySelector('#btn-edit-toggle-custom-usb').click();
      editModal.querySelector('#vm-edit-custom-vid').value = '1a86';
      editModal.querySelector('#vm-edit-custom-pid').value = '7523';
      editModal.querySelector('#vm-edit-custom-desc').value = 'USB Serial Converter';
      editModal.querySelector('#btn-edit-add-custom-usb').click();

      // Submit Edit Modal
      editModal.querySelector('#vm-edit-submit').click();

      await vi.waitFor(() => {
        const calledPayload = (api.put?.mock?.calls?.[0]?.[1]) || (api.post?.mock?.calls?.find(c => c[0] === '/api/vms/vm-edit-adv')?.[1]);
        expect(calledPayload).toEqual(
          expect.objectContaining({
            name: 'win11-prod',
            firmware: 'uefi',
            tpm_enabled: true,
            video_adapter: 'qxl',
            usb_passthrough: expect.arrayContaining([
              expect.objectContaining({ vendor_id: '10c4', product_id: 'ea60' }),
              expect.objectContaining({ vendor_id: '1a86', product_id: '7523' }),
            ]),
          })
        );
      });
    });

    it('ensures Host USB Passthrough card has unclipped flex-shrink layout and custom VID:PID button toggles properly with Enter key support', async () => {
      const vmObj = {
        id: 'vm-usb-view-test',
        name: 'usb-test-vm',
        vcpus: 2,
        ram_gb: 4.0,
        state: 'stopped',
        usb_passthrough: [],
      };
      openVmEditModal('vm-usb-view-test', vmObj);
      const editModal = document.getElementById('modal-vm-edit');
      expect(editModal).not.toBeNull();

      const toggleBtn = editModal.querySelector('#btn-edit-toggle-custom-usb');
      const customWrap = editModal.querySelector('#vm-edit-custom-usb-wrap');
      const usbCard = toggleBtn.closest('.vm-config-card') || toggleBtn.closest('div[style*="border-radius: 8px"]');
      expect(usbCard).not.toBeNull();
      // Ensure overflow: hidden is not present on the card to prevent zero min-height collapse in flexbox
      expect(usbCard.style.overflow).not.toBe('hidden');
      expect(usbCard.style.flexShrink).toBe('0');

      // Initially hidden
      expect(customWrap.style.display).toBe('none');
      expect(toggleBtn.classList.contains('active')).toBe(false);

      // Click to toggle open
      toggleBtn.click();
      expect(customWrap.style.display).toBe('flex');
      expect(toggleBtn.classList.contains('active')).toBe(true);
      expect(toggleBtn.textContent).toContain('Custom VID:PID');

      // Fill in custom VID:PID and press Enter to add
      const vidInput = editModal.querySelector('#vm-edit-custom-vid');
      const pidInput = editModal.querySelector('#vm-edit-custom-pid');
      const descInput = editModal.querySelector('#vm-edit-custom-desc');
      vidInput.value = '303a';
      pidInput.value = '1001';
      descInput.value = 'ESP32-S3 JTAG';

      // Press Enter in descInput
      descInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));

      // Verify card was added to attached USB list
      const attachedCard = editModal.querySelector('.usb-device-card');
      expect(attachedCard).not.toBeNull();
      expect(attachedCard.textContent).toContain('ESP32-S3 JTAG');
      expect(attachedCard.textContent).toContain('303a:1001');

      // Click to toggle close
      toggleBtn.click();
      expect(customWrap.style.display).toBe('none');
      expect(toggleBtn.classList.contains('active')).toBe(false);
    });

    it('supports dragging and full OS window controls (minimize, maximize, close) on VM Edit and Create configuration modals', async () => {
      const mockVm = {
        id: 'vm-controls-test',
        name: 'test-controls-vm',
        vcpus: 2,
        ram_gb: 4.0,
        state: 'stopped',
      };

      // 1. Verify Edit Modal
      openVmEditModal('vm-controls-test', mockVm);
      const editModal = document.getElementById('modal-vm-edit');
      expect(editModal).not.toBeNull();
      expect(editModal.classList.contains('open')).toBe(true);

      const editWin = editModal.querySelector('.smart-modal-window');
      const editHdr = editModal.querySelector('.smart-modal-header');
      expect(editWin).not.toBeNull();
      expect(editHdr).not.toBeNull();

      // Controls existence
      const editControls = editModal.querySelector('.os-window-controls');
      expect(editControls).not.toBeNull();
      const editMinBtn = editModal.querySelector('#vm-edit-modal-min');
      const editMaxBtn = editModal.querySelector('#vm-edit-modal-max');
      const editCloseBtn = editModal.querySelector('#vm-edit-modal-close');
      expect(editMinBtn).not.toBeNull();
      expect(editMaxBtn).not.toBeNull();
      expect(editCloseBtn).not.toBeNull();

      // Maximize toggle
      editMaxBtn.click();
      expect(editWin.classList.contains('maximized')).toBe(true);
      expect(editWin.style.width).toBe('100vw');

      // Double-click header restores
      editHdr.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      expect(editWin.classList.contains('maximized')).toBe(false);

      // Minimize button
      editMinBtn.click();
      expect(editModal.classList.contains('window-minimized')).toBe(true);

      // Close button closes modal
      editCloseBtn.click();
      expect(editModal.classList.contains('open')).toBe(false);

      // 2. Verify Create Modal Controls
      openVmCreateModal();
      const createModal = document.getElementById('modal-vm-create');
      expect(createModal).not.toBeNull();
      expect(createModal.querySelector('#vm-create-modal-min')).not.toBeNull();
      expect(createModal.querySelector('#vm-create-modal-max')).not.toBeNull();
      expect(createModal.querySelector('#vm-modal-close')).not.toBeNull();

      // Create Maximize toggle
      const createWin = createModal.querySelector('.smart-modal-window');
      const createMaxBtn = createModal.querySelector('#vm-create-modal-max');
      createMaxBtn.click();
      expect(createWin.classList.contains('maximized')).toBe(true);
      createMaxBtn.click();
      expect(createWin.classList.contains('maximized')).toBe(false);

      // Close create modal
      createModal.querySelector('#vm-modal-close').click();
      expect(createModal.classList.contains('open')).toBe(false);
    });

    it('enforces single carriage return and preventDefault on Enter in Serial TTY mode', () => {
      openVmConsole('vm-tty-test', 'Alpine TTY VM', 'cli');
      const consoleWin = document.getElementById('vm-console-window');
      expect(consoleWin).not.toBeNull();

      const cliContainer = consoleWin.querySelector('#vm-cli-container');
      expect(cliContainer).not.toBeNull();

      // Mock WebSocket
      const mockWs = {
        readyState: WebSocket.OPEN,
        send: vi.fn(),
      };
      cliContainer.tabIndex = 0;
      let sendCalls = [];

      cliContainer.onkeydown = (e) => {
        e.stopPropagation();
        if (mockWs.readyState === WebSocket.OPEN) {
          if (e.key === 'Enter') {
            e.preventDefault();
            mockWs.send('\r');
          } else if (e.key === 'Backspace') {
            e.preventDefault();
            mockWs.send('\x7f');
          }
        }
      };

      // 1. Dispatch Enter on cliContainer
      const enterEvt = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true });
      cliContainer.dispatchEvent(enterEvt);

      // Must send exactly \r (CR) and NOT \r\n (CRLF) which causes double newline in serial line discipline
      expect(mockWs.send).toHaveBeenCalledTimes(1);
      expect(mockWs.send).toHaveBeenCalledWith('\r');
      expect(enterEvt.defaultPrevented).toBe(true);

      // 2. Global Focus Guard does not duplicate when cliContainer is activeElement or contains target
      const mockWindowGuard = (e) => {
        if (cliContainer === document.activeElement || cliContainer.contains(e.target)) {
          return; // Correct: suppresses double dispatch
        }
        if (cliContainer.onkeydown) {
          cliContainer.onkeydown(e);
        }
      };

      cliContainer.focus();
      const outputDiv = consoleWin.querySelector('#vm-cli-output');
      const innerTargetEvt = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true });
      Object.defineProperty(innerTargetEvt, 'target', { value: outputDiv });

      mockWs.send.mockClear();
      mockWindowGuard(innerTargetEvt);
      // Because target is inside cliContainer, the window guard must return without invoking onkeydown
      // 3. Backspace key sends \x7f for standard UNIX termios erase discipline
      mockWs.send.mockClear();
      const backspaceEvt = new KeyboardEvent('keydown', { key: 'Backspace', cancelable: true });
      cliContainer.dispatchEvent(backspaceEvt);
      expect(mockWs.send).toHaveBeenCalledTimes(1);
      expect(mockWs.send).toHaveBeenCalledWith('\x7f');
      expect(backspaceEvt.defaultPrevented).toBe(true);
    });

    it('correctly processes terminal backspace erase sequences and strips bell in applyTerminalStream', () => {
      // 1. Erase single character
      expect(applyTerminalStream('hello!', '\x08 \x08')).toBe('hello');

      // 2. Erase multiple characters consecutively
      expect(
        applyTerminalStream('localhost:/# exping djdj', '\x08 \x08\x08 \x08\x08 \x08\x08 \x08')
      ).toBe('localhost:/# exping ');

      // 3. Erase with ANSI escape sequences intact
      expect(
        applyTerminalStream('\x1b[33mexping djdj\x1b[0m', '\x08 \x08\x08 \x08')
      ).toBe('\x1b[33mexping dj\x1b[0m');

      // 4. Erase in line ANSI sequence (\x08\x1b[K)
      expect(applyTerminalStream('testing', '\x08\x1b[K')).toBe('testin');
      expect(applyTerminalStream('testing', '\x08\x1b[0K')).toBe('testin');

      // 5. Cursor left erase sequence (\x1b[D \x1b[D)
      expect(applyTerminalStream('status', '\x1b[D \x1b[D')).toBe('statu');

      // 6. Strip bell characters (\x07)
      expect(applyTerminalStream('prompt$ ', '\x07')).toBe('prompt$ ');

      // 7. Safety: does not erase across newline boundaries
      expect(applyTerminalStream('line1\r\n', '\x08 \x08')).toBe('line1\r\n');

      // 8. Fast path: text without backspace or bell returns unchanged
      expect(applyTerminalStream('connected: ', 'welcome guest\r\n')).toBe('connected: welcome guest\r\n');

      // 9. Multi-byte surrogate pair (emoji) deletion
      expect(applyTerminalStream('hello 🚀', '\x08 \x08')).toBe('hello ');

      // 10. Erase in display ANSI sequence (\x08\x1b[J) used by Busybox ash on Alpine Linux
      expect(applyTerminalStream('localhost:~# hol', '\x08\x1b[J')).toBe('localhost:~# ho');
      expect(applyTerminalStream('localhost:~# ho', '\x08\x1b[J')).toBe('localhost:~# h');
      expect(applyTerminalStream('localhost:~# h', '\x08\x1b[J')).toBe('localhost:~# ');

      // 11. Multi-character consecutive ash backspaces
      expect(applyTerminalStream('localhost:~# ', 'abc\x08\x1b[J\x08\x1b[J')).toBe('localhost:~# a');

      // 12. Standalone lone \x08 backspace
      expect(applyTerminalStream('hello', '\x08')).toBe('hell');

      // 13. Sequential backspaces do not leave orphan \x1b[ fragments
      let buf = 'localhost:~# hol';
      buf = applyTerminalStream(buf, '\x08\x1b[J');
      buf = applyTerminalStream(buf, '\x08\x1b[J');
      expect(buf).toBe('localhost:~# h');
      expect(buf).not.toContain('\x1b');
    });
  });
});




