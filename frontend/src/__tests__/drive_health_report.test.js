import { describe, it, expect, vi, afterEach } from 'vitest';
import { api, ApiError } from '../api.js';
import {
  monthsLeft, warrantyText, underWarranty, notesRows, notesForm, reportCsv, driveReportText, safeName, freeName, saveTextToNas, openReportDialog,
} from '../components/drive-health-report.js';

const flush = () => new Promise((r) => setTimeout(r, 0));
const at = new Date(2026, 9, 30); // 30 Oct 2026

afterEach(() => vi.restoreAllMocks());

describe('Drive Health warranty', () => {
  it('counts the months left', () => {
    expect(monthsLeft('2027-05-30', at)).toBe(7);
    expect(monthsLeft('2027-05-29', at)).toBe(6);
    expect(monthsLeft('nope', at)).toBe(null);
    expect(warrantyText('2027-05-30', at)).toBe('Until 2027-05-30 (7 months left)');
    expect(warrantyText('2026-11-10', at)).toBe('Until 2026-11-10 (less than a month left)');
    expect(warrantyText('2026-10-30', at)).toContain('less than a month');
    expect(warrantyText('2024-01-01', at)).toBe('Ended 2024-01-01');
    expect(warrantyText('', at)).toBe('');
    expect(underWarranty({ warranty_until: '2026-10-30' }, at)).toBe(true);
    expect(underWarranty({ warranty_until: '2026-10-29' }, at)).toBe(false);
    expect(underWarranty(null, at)).toBe(false);
  });

  it('shows only the details that are set', () => {
    expect(notesRows({ bought: '2024-01-02', note: 'bay 3' }).map(([k]) => k)).toEqual(['Bought', 'Note']);
    expect(notesRows(null)).toEqual([]);
  });

  it('saves the details from its form', async () => {
    const host = document.createElement('section');
    host.textContent = 'about';
    const put = vi.spyOn(api, 'put').mockResolvedValue({ notes: { bought: '2024-03-01', warranty_until: '2027-03-01' } });
    const saved = vi.fn();
    const form = notesForm(host, 'S1', null, saved);
    form.querySelector('[name=bought]').value = '2024-03-01';
    [...form.querySelectorAll('button')].find((b) => b.textContent === '3 years').click();
    expect(form.querySelector('[name=warranty_until]').value).toBe('2027-03-01');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(put).toHaveBeenCalledWith('/api/drives/notes', { serial: 'S1', bought: '2024-03-01', warranty_until: '2027-03-01', note: '' });
    expect(saved).toHaveBeenCalledWith({ bought: '2024-03-01', warranty_until: '2027-03-01' });
  });

  it('puts the old content back on Cancel and says when saving fails', async () => {
    const host = document.createElement('section');
    host.textContent = 'about';
    const form = notesForm(host, 'S1', { note: 'x' }, vi.fn());
    vi.spyOn(api, 'put').mockRejectedValue(new Error('no'));
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(form.querySelector('[type=submit]').disabled).toBe(false);
    [...form.querySelectorAll('button')].find((b) => b.textContent === 'Cancel').click();
    expect(host.textContent).toBe('about');
  });
});

describe('Drive Health reports', () => {
  it('keeps formulas out of the spreadsheet and adds the warranty', () => {
    const csv = reportCsv([{ dev: 'sda', model: '=HYPERLINK("x")', serial: 'S1', findings: [] }], { S1: { warranty_until: '2027-01-01', note: 'bay 1' } });
    const row = csv.trim().split('\n')[1];
    expect(row).toContain(`"'=HYPERLINK(""x"")"`);
    expect(row).toContain('"2027-01-01","bay 1"');
    expect(csv.split('\n')[0]).toContain('"warranty_until","note"');
  });

  it('writes one drive in full', () => {
    const text = driveReportText({
      drive: { dev: 'sdb', model: 'IronWolf', serial: 'ZA1', role: 'disk1', temp: 38 },
      detail: { raw: 'SMART overall-health: PASSED\n', drive_health: { verdict: 'soon', label_key: 'soon_replace', label: 'Replace soon', identity: { firmware: 'SC60', capacity_bytes: 4e12 }, findings: [{ code: 'x', severity: 'soon', title: 'Parts could not be read', detail: '8 sectors', action: 'Back up' }, { code: 'y', severity: 'ok', title: 'hidden' }] } },
      tests: { history: [{ ts: 1, test_type: 'long', status: 'Completed: read failure' }] },
      history: { samples: 3, temp: { min: 30, max: 41, avg: 35 }, counters: { pending_sectors: { first: 2, last: 8 } } },
      notes: { bought: '2023-01-01', warranty_until: '2028-01-01' },
      now: at,
      counterName: (k) => (k === 'pending_sectors' ? 'Waiting sectors' : k),
    });
    for (const want of ['IronWolf', 'ZA1', 'SC60', 'Replace soon', 'Parts could not be read', 'Back up', 'read failure', 'Waiting sectors: 2 → 8', 'SMART overall-health: PASSED', 'Until 2028-01-01']) {
      expect(text).toContain(want);
    }
    expect(text).not.toContain('hidden');
  });

  it('picks a free, safe file name', () => {
    expect(safeName('drive-WD/Red:4TB?.txt')).toBe('drive-WD-Red-4TB-.txt');
    expect(freeName('r.csv', ['a.txt'])).toBe('r.csv');
    expect(freeName('r.csv', ['R.csv', 'r (2).csv'])).toBe('r (3).csv');
    expect(freeName('notes', ['notes'])).toBe('notes (2)');
  });

  it('saves into the folder through the upload', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ dirs: [{ name: 'drive-health.csv' }] });
    const raw = vi.spyOn(api, 'postRaw').mockResolvedValue(new Response('{}', { status: 200 }));
    const path = await saveTextToNas('/mnt/user/reports/', 'drive-health.csv', 'a,b\n', 'text/csv');
    expect(path).toBe('/mnt/user/reports/drive-health (2).csv');
    expect(raw.mock.calls[0][0]).toBe('/api/fs/upload?path=%2Fmnt%2Fuser%2Freports&filename=drive-health%20(2).csv');
    raw.mockResolvedValue(new Response(JSON.stringify({ detail: 'This upload would go over your space.' }), { status: 507 }));
    await expect(saveTextToNas('/mnt/user/reports', 'x.csv', '')).rejects.toThrow('over your space');
  });

  it('runs the whole dialog', async () => {
    const host = document.createElement('div');
    document.body.append(host);
    vi.spyOn(api, 'get').mockResolvedValue({ dirs: [] });
    const raw = vi.spyOn(api, 'postRaw').mockResolvedValue(new Response('{}', { status: 200 }));
    const drive = { dev: 'sdb', model: 'IronWolf', serial: 'ZA1' };
    const ctx = () => ({ drives: [drive], notes: {}, current: { drive, detail: null, tests: null, history: null } });
    const wrap = openReportDialog(host, ctx, 'drive');
    const name = wrap.querySelector('input[name=name]');
    expect(name.value).toMatch(/^drive-IronWolf-ZA1-\d{4}-\d{2}-\d{2}\.txt$/);
    wrap.querySelector('input[value=all]').click();
    wrap.querySelector('input[value=all]').dispatchEvent(new Event('change'));
    expect(name.value).toMatch(/^drive-health-.*\.csv$/);
    wrap.querySelector('input[name=dir]').value = '/mnt/user/r';
    [...wrap.querySelectorAll('button')].find((b) => b.textContent === 'Save').click();
    await flush();
    await flush();
    expect(raw).toHaveBeenCalled();
    expect(wrap.textContent).toContain('Saved as /mnt/user/r/drive-health-');
    const fm = vi.fn();
    window.openFileManager = fm;
    [...wrap.querySelectorAll('button')].find((b) => b.textContent === 'Show in File Explorer').click();
    expect(fm).toHaveBeenCalledWith('/mnt/user/r');
    expect(host.querySelector('.dh-dialog-wrap')).toBe(null);
    delete window.openFileManager;
    host.remove();
  });

  it('says so when the folder\'s disk stays asleep, and closes on Escape', async () => {
    const host = document.createElement('div');
    document.body.append(host);
    vi.spyOn(api, 'get').mockRejectedValue(new ApiError('Cancelled', { status: 428, error: 'cancelled' }));
    const wrap = openReportDialog(host, () => ({ drives: [], notes: {}, current: null }));
    expect(wrap.querySelector('input[value=drive]').disabled).toBe(true);
    [...wrap.querySelectorAll('button')].find((b) => b.textContent === 'Save').click();
    await flush();
    expect(wrap.textContent).toContain('disk is asleep');
    wrap.querySelector('input[name=dir]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(host.querySelector('.dh-dialog-wrap')).toBe(null);
    host.remove();
  });
});
