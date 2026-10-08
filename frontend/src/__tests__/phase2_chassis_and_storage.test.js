import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getThermalLevel,
  generateSmartSparklineSvg,
  renderChassisTwin,
  triggerLocateDisk,
  renderStorageTopologyTree,
  playChirp
} from '../components/chassis-visualizer.js';
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

  it('renders parametric bays for HDD and M.2 NVMe drives', () => {
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
});
