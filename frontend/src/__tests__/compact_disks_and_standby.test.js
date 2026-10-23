import { readStyleCss } from './helpers/read-style-css.js';
import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'fs';
import path from 'path';
import { formatDiskDisplayName, diskTile, renderDisks, applyStats } from '../components/dashboard.js';
import { state } from '../state.js';

describe('Compact Disks Display & Standby Safety Suite', () => {
  const cssContent = readStyleCss();

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="screen">
        <header>
          <div class="h-left">
            <span class="nas-name" id="nasName">NAS</span>
            <span class="pill" id="statusPill"><span class="pill-dot"></span><span id="statusText">– OK</span></span>
          </div>
        </header>
        <section class="disks card-disks" id="diskRow"></section>
      </div>
    `;
    state.lcdTheme = 'cyber';
  });

  describe('formatDiskDisplayName', () => {
    it('preserves SATA disk names without change', () => {
      expect(formatDiskDisplayName('sda')).toBe('sda');
      expect(formatDiskDisplayName('sdb')).toBe('sdb');
      expect(formatDiskDisplayName('sdh')).toBe('sdh');
      expect(formatDiskDisplayName('/dev/sdc')).toBe('sdc');
    });

    it('compacts NVMe disk names cleanly to avoid horizontal truncation', () => {
      expect(formatDiskDisplayName('nvme0n1')).toBe('nv0');
      expect(formatDiskDisplayName('nvme1n1')).toBe('nv1');
      expect(formatDiskDisplayName('/dev/nvme2n1')).toBe('nv2');
      expect(formatDiskDisplayName('nvme0')).toBe('nv0');
      expect(formatDiskDisplayName('nvme1')).toBe('nv1');
      expect(formatDiskDisplayName('nvme0n2')).toBe('nv0n2');
    });

    it('compacts eMMC device names', () => {
      expect(formatDiskDisplayName('mmcblk0')).toBe('mmc0');
      expect(formatDiskDisplayName('mmcblk0p1')).toBe('mmc0');
    });

    it('handles empty and null values safely', () => {
      expect(formatDiskDisplayName('')).toBe('');
      expect(formatDiskDisplayName(null)).toBe('');
      expect(formatDiskDisplayName(undefined)).toBe('');
    });
  });

  describe('diskTile generation', () => {
    it('renders compact display name inside .dn element', () => {
      const tile = diskTile({ name: 'nvme0n1', role: 'cache', temp: 42, health: 'ok' });
      expect(tile.querySelector('.dn').textContent).toBe('nv0');
      expect(tile.dataset.dev).toBe('nvme0n1');
    });

    it('renders STANDBY badge and standby classes when disk is spun down', () => {
      const tile = diskTile({ name: 'sda', role: 'data', temp: null, health: 'standby', standby: true });
      expect(tile.classList.contains('disk-standby')).toBe(true);
      expect(tile.querySelector('.standby-badge')).not.toBeNull();
      expect(tile.querySelector('.standby-badge').textContent).toBe('STANDBY');
      expect(tile.querySelector('.dn').textContent).toBe('sda');
    });
  });

  describe('renderDisks compact mode', () => {
    it('activates compact mode when 7 or more disks exist', () => {
      const disks = [
        { name: 'sda', role: 'data', temp: 35, health: 'ok' },
        { name: 'sdb', role: 'data', temp: 35, health: 'ok' },
        { name: 'sdc', role: 'data', temp: 35, health: 'ok' },
        { name: 'sdd', role: 'data', temp: 35, health: 'ok' },
        { name: 'sde', role: 'data', temp: 35, health: 'ok' },
        { name: 'sdf', role: 'data', temp: 35, health: 'ok' },
        { name: 'nvme0n1', role: 'cache', temp: 40, health: 'ok' },
      ];
      renderDisks(disks);
      const row = document.getElementById('diskRow');
      expect(row.classList.contains('compact')).toBe(true);
      expect(row.querySelector('[data-dev="nvme0n1"] .dn').textContent).toBe('nv0');
    });
  });

  describe('Compact CSS styling invariants', () => {
    const lcdDirectCssPath = path.resolve(__dirname, '../lcd-direct.css');
    const lcdDirectCssContent = fs.readFileSync(lcdDirectCssPath, 'utf8');

    it('hides redundant zZz, disk-ic, and io-dot in compact mode to free horizontal space for disk name', () => {
      expect(cssContent).toMatch(/\.disks\.compact\s+\.standby-zzz\s*\{\s*display:\s*none\s*!important;\s*\}/);
      expect(cssContent).toMatch(/\.disks\.compact\s+\.disk-ic\s*\{\s*display:\s*none\s*!important;\s*\}/);
      expect(cssContent).toMatch(/\.disks\.compact\s+\.io-dot\s*\{\s*display:\s*none\s*!important;\s*\}/);
    });

    it('scales standby-badge down to 7.5px with overflow clipping to prevent "Y" overflow', () => {
      expect(cssContent).toMatch(/\.disks\.compact\s+\.standby-badge\s*\{[^}]*font-size:\s*7\.5px/);
      expect(cssContent).toMatch(/\.disks\.compact\s+\.standby-badge\s*\{[^}]*overflow:\s*hidden/);
      expect(cssContent).toMatch(/\.disks\.compact\s+\.standby-badge\s*\{[^}]*text-align:\s*center/);
    });

    it('enforces tight gaps and padding on compact disk elements', () => {
      expect(cssContent).toMatch(/\.disks\.compact\s*\{\s*gap:\s*4px;\s*\}/);
      expect(cssContent).toMatch(/\.disks\.compact\s+\.disk\s*\{\s*padding:\s*2px\s+2\.5px;\s*\}/);
    });

    it('enforces compact rules on physical LCD via lcd-direct.css overrides', () => {
      expect(lcdDirectCssContent).toMatch(/body\.lcd-direct[\s\S]*?\.disks\.compact[\s\S]*?gap:\s*4px\s*!important/);
      expect(lcdDirectCssContent).toMatch(/body\.lcd-direct[\s\S]*?\.disks\.compact\s+\.disk[\s\S]*?padding:\s*2px\s+2\.5px\s*!important/);
      expect(lcdDirectCssContent).toMatch(/body\.lcd-direct[\s\S]*?\.disks\.compact\s+\.disk-ic[\s\S]*?display:\s*none\s*!important/);
      expect(lcdDirectCssContent).toMatch(/body\.lcd-direct[\s\S]*?\.disks\.compact\s+\.io-dot[\s\S]*?display:\s*none\s*!important/);
    });
  });

  describe('Status Pill Standby Health Logic', () => {
    it('keeps statusPill green (no warn class) when drives are in standby and rest are OK', () => {
      const pill = document.getElementById('statusPill');
      const disks = [
        { name: 'sda', role: 'data', temp: null, health: 'standby', standby: true },
        { name: 'sdb', role: 'data', temp: null, health: 'standby', standby: true },
        { name: 'nvme0n1', role: 'cache', temp: 38, health: 'ok' },
      ];
      applyStats({
        name: 'ZETTNEXT',
        status: '3 OK',
        ip: '192.168.1.50',
        storage: { pct: 40, used: '4TB', total: '10TB' },
        cpu: { temp: 45, util: 12 },
        mem: { pct: 30, used_gb: 8.0, total_gb: 32.0, used: '8G', total: '32G' },
        fans: [1200],
        disks,
        uptime: '2h',
      });

      expect(pill.className).toBe('pill');
      expect(pill.classList.contains('warn')).toBe(false);
    });

    it('triggers warn class on statusPill when a drive has degraded health or high temperature', () => {
      const pill = document.getElementById('statusPill');
      const disks = [
        { name: 'sda', role: 'data', temp: null, health: 'standby', standby: true },
        { name: 'sdb', role: 'data', temp: 65, health: 'crit' },
        { name: 'nvme0n1', role: 'cache', temp: 38, health: 'ok' },
      ];
      applyStats({
        name: 'ZETTNEXT',
        status: '1 ALERT',
        ip: '192.168.1.50',
        storage: { pct: 40, used: '4TB', total: '10TB' },
        cpu: { temp: 45, util: 12 },
        mem: { pct: 30, used_gb: 8.0, total_gb: 32.0, used: '8G', total: '32G' },
        fans: [1200],
        disks,
        uptime: '2h',
      });

      expect(pill.classList.contains('warn')).toBe(true);
    });
  });
});
