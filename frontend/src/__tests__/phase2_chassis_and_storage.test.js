import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  getThermalLevel,
  generateSmartSparklineSvg,
  renderChassisTwin,
  fetchAndRenderChassisTwin,
  openChassisConfigModal,
  triggerLocateDisk,
  renderStorageTopologyTree,
  playChirp
} from '../components/chassis-visualizer.js';
import { fetchAndRenderDisksInventory } from '../components/management.js';
import { api } from '../api.js';

describe('Phase 2: Thermal Heatmap Level Calculations', () => {
  it('correctly maps disk temperatures to 5-tier thermal heatmap tokens', () => {
    // Standby drive
    const stby = getThermalLevel(null, true);
    expect(stby.cls).toBe('standby');
    expect(stby.text).toBe('STANDBY');

    // Cool drive (< 35C)
    const cool = getThermalLevel(28, false);
    expect(cool.cls).toBe('cool');
    expect(cool.color).toBe('#38bdf8');
    expect(cool.text).toBe('28°C');

    // Optimal healthy drive (35 - 45C)
    const ok = getThermalLevel(38, false);
    expect(ok.cls).toBe('ok');
    expect(ok.color).toBe('#3bf58b');
    expect(ok.text).toBe('38°C');

    // Warm drive (46 - 52C)
    const warn = getThermalLevel(49, false);
    expect(warn.cls).toBe('warn');
    expect(warn.color).toBe('#f5b731');
    expect(warn.text).toBe('49°C');

    // Critical hot drive (>= 53C)
    const crit = getThermalLevel(56, false);
    expect(crit.cls).toBe('crit');
    expect(crit.color).toBe('#f0553b');
    expect(crit.text).toBe('56°C');
  });
});

describe('Phase 2: Zero-Bloat S.M.A.R.T. Velocity Sparkline Generator', () => {
  it('renders a fallback message when no history points are available', () => {
    const emptySvg = generateSmartSparklineSvg([], 280, 50);
    expect(emptySvg).toContain('<svg class="smart-sparkline-svg"');
    expect(emptySvg).toContain('No historical data recorded');
  });

  it('generates smooth SVG path geometry with healthy green gradient for stable disks', () => {
    const points = [
      { ts: 1000, temp: 34, realloc: 0, pending: 0 },
      { ts: 2000, temp: 35, realloc: 0, pending: 0 },
      { ts: 3000, temp: 34, realloc: 0, pending: 0 }
    ];
    const svg = generateSmartSparklineSvg(points, 300, 60);
    expect(svg).toContain('<path');
    expect(svg).toContain('stroke="#3bf58b"');
    expect(svg).toContain('<circle');
  });

  it('highlights warning amber gradient when reallocated/pending sectors exist', () => {
    const points = [
      { ts: 1000, temp: 34, realloc: 0, pending: 0 },
      { ts: 2000, temp: 35, realloc: 2, pending: 0 },
      { ts: 3000, temp: 36, realloc: 5, pending: 1 }
    ];
    const svg = generateSmartSparklineSvg(points, 300, 60);
    expect(svg).toContain('stroke="#f5b731"');
  });
});

describe('Phase 2: Parametric Chassis Twin & Locate Strobe', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    container.remove();
    document.querySelectorAll('#chassis-config-modal-overlay').forEach(el => el.remove());
  });

  it('renders parametric bays for HDD and M.2 NVMe drives from raw disks list', () => {
    const testDisks = [
      { dev: 'sda', model: 'WDC WD140EDFZ', temp: 36, health: 'ok', size_formatted: '14 TB' },
      { dev: 'sdb', model: 'Seagate IronWolf', temp: 42, health: 'ok', size_formatted: '8 TB' },
      { dev: 'sdc', model: 'TOSHIBA MG08', temp: null, standby: true, health: 'standby', size_formatted: '16 TB' },
      { dev: 'nvme0n1', model: 'Samsung 980 PRO', temp: 44, percentage_used: 12, health: 'ok' }
    ];

    renderChassisTwin(container, testDisks);

    expect(container.querySelector('.chassis-enclosure-faceplate')).not.toBeNull();
    const baySlots = container.querySelectorAll('.chassis-bay-slot');
    expect(baySlots.length).toBeGreaterThanOrEqual(4);

    const m2Twin = container.querySelector('.m2-motherboard-twin');
    expect(m2Twin).not.toBeNull();
    expect(m2Twin.textContent).toContain('Samsung 980 PRO');
  });

  it('renders dynamic profile grid classes and custom bay labels from /api/chassis/config', () => {
    const chassisConfig = {
      profile: 'rackmount_backplane',
      total_bays: 8,
      chassis_model: 'ENTERPRISE RACK (8-BAY)',
      bays: [
        {
          slot_index: 1,
          is_populated: true,
          custom_label: 'Parity 1',
          disk: {
            dev: 'sda',
            model: 'Seagate Exos 22TB',
            serial: 'ZX20B50W',
            size_formatted: '20.0 TB',
            transport: 'sata',
            controller_driver: 'ahci',
            temp: 42,
            health: 'ok',
            standby: false
          }
        },
        {
          slot_index: 2,
          is_populated: false,
          custom_label: 'Spare Tray',
          disk: null
        }
      ],
      nvme_slots: [
        {
          slot_index: 1,
          disk: {
            dev: 'nvme1n1',
            model: 'WD Black SN770 1TB',
            temp: 44,
            wear: 5
          }
        }
      ],
      available_drives: []
    };

    renderChassisTwin(container, chassisConfig.bays, { chassisConfig });

    const grid = container.querySelector('.chassis-bay-grid');
    expect(grid.classList.contains('mode-rackmount')).toBe(true);

    const bay1 = container.querySelector('.chassis-bay-slot[data-bay="1"]');
    expect(bay1.textContent).toContain('Parity 1');
    expect(bay1.textContent).toContain('Seagate Exos');

    const slotsBtn = container.querySelector('#chassis-open-slots-btn');
    expect(slotsBtn).not.toBeNull();
  });

  it('triggers locate disk API and activates visual strobe with audio chirp', async () => {
    const apiSpy = vi.spyOn(api, 'request').mockResolvedValue({ ok: true, json: async () => ({ success: true }) });
    const slot = document.createElement('div');
    container.appendChild(slot);

    await triggerLocateDisk('sda', slot);

    expect(apiSpy).toHaveBeenCalledWith('/api/disk/locate', {
      method: 'POST',
      body: { dev: 'sda', duration: 5 }
    });
    expect(slot.classList.contains('strobe-active')).toBe(true);

    apiSpy.mockRestore();
  });

  it('renders hierarchical Storage Topology Tree with parity and data partitions', () => {
    const testDisks = [
      { dev: 'sda', role: 'os', temp: 36 },
      { dev: 'sdb', role: 'data', temp: 38 },
      { dev: 'nvme0n1', role: 'cache', temp: 41 }
    ];

    renderStorageTopologyTree(container, testDisks, { state: 'STARTED' });

    expect(container.querySelector('.storage-topology-tree')).not.toBeNull();
    expect(container.textContent).toContain('PARITY PROTECTION');
    expect(container.textContent).toContain('DATA ARRAY POOL');
    expect(container.textContent).toContain('NVME / SSD CACHE POOL');
  });

  it('opens Chassis Slots Mapping modal and saves user customization', async () => {
    const apiPostSpy = vi.spyOn(api, 'request').mockResolvedValue({ ok: true, json: async () => ({ success: true }) });

    const config = {
      profile: 'tower_desktop',
      total_bays: 4,
      available_drives: [
        { dev: 'sda', canonical_id: 'ata-ST22000NM_123', model: 'ST22000NM', serial: '123', size_formatted: '20 TB' },
        { dev: 'sdb', canonical_id: 'ata-ST22000NM_456', model: 'ST22000NM', serial: '456', size_formatted: '20 TB' }
      ],
      bays: [
        { slot_index: 1, canonical_id: 'ata-ST22000NM_123', custom_label: 'Parity' }
      ]
    };

    openChassisConfigModal(config);

    const modal = document.getElementById('chassis-config-modal-overlay');
    expect(modal).not.toBeNull();
    expect(modal.style.display).toBe('flex');

    const profileSel = modal.querySelector('#chassis-profile-select');
    expect(profileSel.value).toBe('tower_desktop');

    // Click auto-assign sequentially
    const autoBtn = modal.querySelector('#chassis-auto-assign-btn');
    autoBtn.click();

    // Click save
    const saveBtn = modal.querySelector('#chassis-config-save-btn');
    await saveBtn.click();

    expect(apiPostSpy).toHaveBeenCalledWith('/api/chassis/bay_map', expect.objectContaining({
      method: 'POST'
    }));

    apiPostSpy.mockRestore();
  });

  it('fetchAndRenderDisksInventory populates HAL disks table', async () => {
    const mockTbody = document.createElement('tbody');
    mockTbody.id = 'mgmt-disks-inventory-tbody';
    document.body.appendChild(mockTbody);

    const apiSpy = vi.spyOn(api, 'request').mockResolvedValue({
      ok: true,
      json: async () => ({
        bays: [
          {
            slot_index: 1,
            disk: {
              dev: 'sda',
              model: 'Seagate IronWolf 12TB',
              serial: 'WXYZ9876',
              transport: 'sata',
              controller_driver: 'ahci',
              size_formatted: '12.0 TB',
              temp: 39,
              health: 'ok',
              standby: false
            }
          }
        ],
        nvme_slots: [
          {
            slot_index: 1,
            disk: {
              dev: 'nvme0n1',
              model: 'Samsung 990 PRO 2TB',
              serial: 'S990PRO123',
              transport: 'nvme',
              controller_driver: 'nvme',
              size_formatted: '1.8 TB',
              temp: 45,
              health: 'ok',
              standby: false
            }
          }
        ]
      })
    });

    await fetchAndRenderDisksInventory();

    expect(mockTbody.querySelectorAll('tr').length).toBe(2);
    expect(mockTbody.textContent).toContain('/dev/sda');
    expect(mockTbody.textContent).toContain('/dev/nvme0n1');
    expect(mockTbody.textContent).toContain('Seagate IronWolf');
    expect(mockTbody.textContent).toContain('Samsung 990 PRO');

    apiSpy.mockRestore();
    mockTbody.remove();
  });
});
