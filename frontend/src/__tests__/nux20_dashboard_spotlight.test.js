/** NUX-20: drive titles on the dashboard and Spotlight's commands read in the person's language. */
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { setLanguage } from '../i18n.js';
import { driveLabel, driveTileTitle, driveChipTitle, updateRowTelemetryBadges, updateUnraidTelemetry, updateCopyToast, updateMediaSlots } from '../components/dashboard.js';
import { initSpotlight, openSpotlight, filterSpotlightResults, closeSpotlight } from '../components/spotlight.js';

describe('drive titles (NUX-20)', () => {
  it('name the drive, its parity role and what a click does', () => {
    const d = { name: 'disk1' };
    expect(driveLabel(d, false)).toBe('disk1');
    expect(driveLabel(d, true)).toBe('disk1 [PARITY]');
    expect(driveTileTitle(d, true, true)).toBe('disk1 [PARITY] is asleep (spun down)');
    expect(driveTileTitle(d, false, false)).toBe('Click to see the health of disk1');
    expect(driveTileTitle({ name: 'disk2', risk: 'critical' }, false, false)).toBe('disk2: likely to fail soon. Back up its data and plan a replacement.');
    expect(driveTileTitle({ name: 'disk2', risk: 'high', risk_advice: 'Replace it now.' }, false, false)).toBe('disk2: likely to fail soon. Replace it now.');
    expect(driveChipTitle(d, false, false, 'sdb')).toBe('Drive disk1 (sdb): click to see its health');
    expect(driveChipTitle(d, false, true, 'sdb')).toBe('disk1 is asleep (spun down)');
  });

  describe('in German', () => {
    beforeAll(async () => { await setLanguage('de'); });
    afterAll(async () => { await setLanguage('en'); });

    it('translates the titles and Spotlight’s typed commands', () => {
      expect(driveTileTitle({ name: 'disk1' }, true, true)).toBe('disk1 [PARITÄT] schläft (abgeschaltet)');
      document.body.innerHTML = '';
      initSpotlight();
      openSpotlight();
      const results = () => document.getElementById('spotlight-results').textContent;
      filterSpotlightResults('>snap pool tank');
      expect(results()).toContain('Pool-Snapshot: tank');
      filterSpotlightResults('>locate sdb');
      expect(results()).toContain('Laufwerk finden: sdb');
      filterSpotlightResults('? Nudelrezept');
      expect(results()).toContain('Kib fragen: „Nudelrezept“');
      filterSpotlightResults('qqqqzzzz-nothing');
      expect(results()).toBe('Nichts gefunden.');
      closeSpotlight();
    });
  });
});


const text = (id) => document.getElementById(id).textContent;

describe('dashboard badges, array, copy window and card reader (NUX-20)', () => {
  it('shows passive fans and counts drives', () => {
    document.body.innerHTML = '<span id="telemetry-badge-fans"></span><span id="telemetry-badge-disks"></span>';
    updateRowTelemetryBadges({ fans: [0, 0], fan_control: { zone1_zero_rpm: true }, disks: [{}] });
    expect(text('telemetry-badge-fans')).toBe('0 RPM • PASSIVE');
    expect(text('telemetry-badge-disks')).toBe('1 drive active');
    updateRowTelemetryBadges({ fans: [900], disks: [{}, {}] });
    expect(text('telemetry-badge-fans')).toBe('900 RPM');
    expect(text('telemetry-badge-disks')).toBe('2 drives active');
  });

  it('describes the Unraid array, the mover and a parity check', () => {
    document.body.innerHTML = `
      <div id="unraid-array-pill"><span id="unraid-array-status"></span><span id="unraid-array-dot"></span></div>
      <div id="unraid-mover-pill"><span id="unraid-mover-status"></span></div>
      <div id="unraid-storage-badge"><span id="unraid-storage-text"></span></div>
      <div id="unraid-parity-box"><div id="unraid-parity-bar"></div><span id="unraid-parity-txt"></span></div>`;
    updateUnraidTelemetry({ available: true, mover: { active: true, remain_files: 3 }, parity_check: { active: true, progress_pct: 40, errors: 1 } });
    expect(text('unraid-array-status')).toBe('STARTED');
    expect(text('unraid-mover-status')).toBe('3 files left');
    expect(text('unraid-storage-text')).toBe('UNRAID: STARTED');
    expect(text('unraid-parity-txt')).toBe('Parity: 40% (1 error)');
    updateUnraidTelemetry({ available: true, state: 'STOPPED', mover: { active: true }, parity_check: { active: true } });
    expect(text('unraid-array-status')).toBe('STOPPED');
    expect(text('unraid-mover-status')).toBe('Active');
    expect(text('unraid-storage-text')).toBe('UNRAID: STOPPED');
    expect(text('unraid-parity-txt')).toBe('Parity: 0% (0 errors)');
  });

  it('shows what a copy is doing and how long is left', () => {
    document.body.innerHTML = `
      <div id="copy-toast"><div class="smart-modal-body"></div><span id="copy-toast-pct"></span><div id="copy-toast-bar"></div>
      <span id="copy-toast-file"></span><span id="copy-toast-time"></span></div>`;
    const now = Date.now() / 1000;
    updateCopyToast({ active: true, status: 'copying', progress: { total: 100 * 1024 * 1024, copied: 50 * 1024 * 1024, start: now - 10, files_total: 3, files_done: 1 } });
    expect(text('copy-toast-file')).toBe('Preparing files…');
    expect(text('copy-toast-time')).toMatch(/^2 files left • \d+\.\d MB\/s • ~\d+ min \d+ s$/);
    updateCopyToast({ active: true, status: 'copying', progress: { total: 100, copied: 50, start: now - 10, file: 'a.jpg' } });
    expect(text('copy-toast-file')).toBe('a.jpg');
    expect(text('copy-toast-time')).toMatch(/^\d+\.\d MB\/s/);
  });

  it('names the memory card in each slot', () => {
    document.body.innerHTML = '<span id="media-slot-info-badge"></span>';
    updateMediaSlots({ sd: { size: 64e9 } });
    expect(text('media-slot-info-badge')).toBe('SD: 64.0 GB');
    updateMediaSlots({ sd: { size: 64e9, ejected: true } });
    expect(text('media-slot-info-badge')).toBe('SD: 64.0 GB (EJECTED)');
    updateMediaSlots({ tf: { size: 32e9 } });
    expect(text('media-slot-info-badge')).toBe('TF: 32.0 GB');
    updateMediaSlots({ tf: { size: 32e9, ejected: true } });
    expect(text('media-slot-info-badge')).toBe('TF: 32.0 GB (EJECTED)');
    updateMediaSlots({});
    expect(text('media-slot-info-badge')).toBe('SLOTS EMPTY');
  });
});
