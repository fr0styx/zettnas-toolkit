import { describe, it, expect, beforeEach } from 'vitest';
import { updateManagementTelemetry } from '../components/management.js';

describe('Hardware Subsystem & GPU Transcode Cockpit (Option C & D)', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="mgmt-sec-hardware">
        <label id="mgmt-host-status-label">HOST SUBSYSTEM STATUS</label>
        
        <div class="unraid-details-grid" style="display:none;">
          <span id="mgmt-unraid-state">-</span>
          <span id="mgmt-unraid-server">-</span>
          <span id="mgmt-unraid-version">-</span>
          <span id="mgmt-unraid-disks">-</span>
          <span id="mgmt-unraid-parity">-</span>
          <span id="mgmt-unraid-mover">-</span>
        </div>

        <div class="generic-details-grid" style="display:none;">
          <span id="mgmt-generic-os">-</span>
          <span id="mgmt-generic-host">-</span>
          <span id="mgmt-generic-uptime">-</span>
          <span id="mgmt-generic-cpu">-</span>
          <span id="mgmt-generic-load">-</span>
          <span id="mgmt-generic-engine">-</span>
        </div>

        <div id="mgmt-board-details-grid">
          <span id="mgmt-board-name">-</span>
          <span id="mgmt-bios-ver">-</span>
          <span id="mgmt-cpu-gov">-</span>
          <span id="mgmt-cpu-cores">-</span>
        </div>

        <span id="mgmt-gpu-status-badge">STANDBY</span>
        <span id="mgmt-gpu-name">-</span>
        <span id="mgmt-gpu-driver">-</span>
        <span id="mgmt-gpu-node">-</span>
        <span id="mgmt-gpu-accel">-</span>
        <div id="mgmt-gpu-codecs-list"></div>

        <div id="mgmt-npu-container">
          <span id="mgmt-npu-status-badge">STANDBY</span>
          <span id="mgmt-npu-name">-</span>
          <span id="mgmt-npu-driver">-</span>
          <span id="mgmt-npu-node">-</span>
          <span id="mgmt-npu-clock">-</span>
          <span id="mgmt-npu-accel">-</span>
          <div id="mgmt-npu-frameworks-list"></div>
        </div>
      </div>
    `;
  });

  it('renders real Unraid array status and updates dynamic header when Unraid is available', () => {
    const mockStats = {
      unraid: {
        available: true,
        state: 'STARTED',
        color: 'green-on',
        version: '7.3.2',
        server_name: 'Ark',
        model: 'D6U',
        disks: { total: 12, disabled: 0, invalid: 0 },
        parity_check: { active: false, errors: 0 },
        mover: { active: false }
      },
      name: 'Ark',
      motherboard: {
        vendor: 'Zettlab',
        board: 'WY120',
        bios_version: 'WY120V016',
        bios_date: '05/09/2026'
      },
      cpu: {
        model: 'Intel Core Ultra 5 125H',
        cores: 18,
        governor: 'performance'
      }
    };

    updateManagementTelemetry(mockStats);

    const unraidGrid = document.querySelector('.unraid-details-grid');
    const genericGrid = document.querySelector('.generic-details-grid');
    const hostLabel = document.getElementById('mgmt-host-status-label');
    const stateEl = document.getElementById('mgmt-unraid-state');
    const srvEl = document.getElementById('mgmt-unraid-server');
    const verEl = document.getElementById('mgmt-unraid-version');

    expect(unraidGrid.style.display).toBe('grid');
    expect(genericGrid.style.display).toBe('none');
    expect(hostLabel.textContent).toContain('UNRAID');
    expect(stateEl.textContent).toContain('STARTED');
    expect(srvEl.textContent).toContain('Ark (D6U)');
    expect(verEl.textContent).toBe('Unraid 7.3.2');
  });

  it('renders real Host System & Kernel topology when on Generic Linux', () => {
    const mockStats = {
      unraid: { available: false },
      system: {
        os: 'Debian GNU/Linux 13 (trixie)',
        kernel: '6.18.38-generic',
        uptime_str: '5d 12h 30m',
        hostname: 'Ark-Node'
      },
      cpu: {
        model: 'Intel(R) Core(TM) Ultra 5 125H',
        cores: 18,
        governor: 'performance',
        load_avg: [0.15, 0.25, 0.35]
      },
      storage: {
        engine: 'Btrfs Native Subvolumes'
      }
    };

    updateManagementTelemetry(mockStats);

    const unraidGrid = document.querySelector('.unraid-details-grid');
    const genericGrid = document.querySelector('.generic-details-grid');
    const hostLabel = document.getElementById('mgmt-host-status-label');
    const osEl = document.getElementById('mgmt-generic-os');
    const cpuEl = document.getElementById('mgmt-generic-cpu');
    const loadEl = document.getElementById('mgmt-generic-load');
    const engineEl = document.getElementById('mgmt-generic-engine');

    expect(unraidGrid.style.display).toBe('none');
    expect(genericGrid.style.display).toBe('grid');
    expect(hostLabel.textContent).toBe('HOST SYSTEM & KERNEL TOPOLOGY');
    expect(osEl.textContent).toBe('Debian GNU/Linux 13 (trixie)');
    expect(cpuEl.textContent).toBe('Intel Core Ultra 5 125H (18T)');
    expect(loadEl.textContent).toBe('0.15, 0.25, 0.35');
    expect(engineEl.textContent).toBe('Btrfs Native Subvolumes');
  });

  it('renders Motherboard DMI firmware and CPU scaling governor (Option D)', () => {
    const mockStats = {
      motherboard: {
        vendor: 'Zettlab',
        board: 'WY120',
        bios_version: 'WY120V016',
        bios_date: '05/09/2026'
      },
      cpu: {
        governor: 'powersave',
        cores: 18
      }
    };

    updateManagementTelemetry(mockStats);

    const boardEl = document.getElementById('mgmt-board-name');
    const biosEl = document.getElementById('mgmt-bios-ver');
    const govEl = document.getElementById('mgmt-cpu-gov');
    const coresEl = document.getElementById('mgmt-cpu-cores');

    expect(boardEl.textContent).toBe('Zettlab WY120');
    expect(biosEl.textContent).toBe('WY120V016 (05/09/2026)');
    expect(govEl.textContent).toBe('powersave');
    expect(coresEl.textContent).toBe('18 Threads / Cores');
  });

  it('renders GPU Hardware Transcode Engine telemetry and supported codecs (Option D)', () => {
    const mockStats = {
      gpu: {
        present: true,
        vendor: 'Intel',
        model: 'Intel Arc Graphics (Meteor Lake-P GT1)',
        driver: 'i915',
        render_node: '/dev/dri/renderD128',
        acceleration: 'Intel QuickSync Video (QSV) • VA-API 1.20',
        codecs: ['AV1', 'HEVC 10-bit', 'H.264', 'VP9'],
        ready: true
      }
    };

    updateManagementTelemetry(mockStats);

    const badge = document.getElementById('mgmt-gpu-status-badge');
    const nameEl = document.getElementById('mgmt-gpu-name');
    const driverEl = document.getElementById('mgmt-gpu-driver');
    const nodeEl = document.getElementById('mgmt-gpu-node');
    const accelEl = document.getElementById('mgmt-gpu-accel');
    const codecsEl = document.getElementById('mgmt-gpu-codecs-list');

    expect(badge.textContent).toBe('ACCELERATION ACTIVE');
    expect(nameEl.textContent).toBe('Intel Arc Graphics (Meteor Lake-P GT1)');
    expect(driverEl.textContent).toBe('Driver: i915');
    expect(nodeEl.textContent).toBe('/dev/dri/renderD128');
    expect(accelEl.textContent).toContain('QuickSync');
    expect(codecsEl.querySelectorAll('.gpu-codec-tag').length).toBe(4);
    expect(codecsEl.textContent).toContain('AV1');
    expect(codecsEl.textContent).toContain('HEVC 10-bit');
  });

  it('renders NPU Neural Acceleration Engine telemetry and AI frameworks', () => {
    const mockStats = {
      npu: {
        present: true,
        vendor: 'Intel',
        model: 'Intel AI Boost NPU (Meteor Lake VPU 3720)',
        driver: 'intel_vpu',
        render_node: '/dev/accel/accel0',
        max_freq_mhz: 1400,
        acceleration: 'Intel OpenVINO • ONNX Runtime • DirectML',
        frameworks: ['OpenVINO', 'ONNX Runtime', 'DirectML', 'PyTorch IPEX'],
        ready: true
      }
    };

    updateManagementTelemetry(mockStats);

    const container = document.getElementById('mgmt-npu-container');
    const badge = document.getElementById('mgmt-npu-status-badge');
    const nameEl = document.getElementById('mgmt-npu-name');
    const driverEl = document.getElementById('mgmt-npu-driver');
    const nodeEl = document.getElementById('mgmt-npu-node');
    const clockEl = document.getElementById('mgmt-npu-clock');
    const accelEl = document.getElementById('mgmt-npu-accel');
    const fwEl = document.getElementById('mgmt-npu-frameworks-list');

    expect(container.style.display).toBe('block');
    expect(badge.textContent).toBe('NPU ACTIVE');
    expect(nameEl.textContent).toBe('Intel AI Boost NPU (Meteor Lake VPU 3720)');
    expect(driverEl.textContent).toBe('Driver: intel_vpu');
    expect(nodeEl.textContent).toBe('/dev/accel/accel0');
    expect(clockEl.textContent).toBe('1400 MHz');
    expect(accelEl.textContent).toContain('OpenVINO');
    expect(fwEl.querySelectorAll('.gpu-codec-tag').length).toBe(4);
    expect(fwEl.textContent).toContain('ONNX Runtime');
    expect(fwEl.textContent).toContain('DirectML');
  });
});
