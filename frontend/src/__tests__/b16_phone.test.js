import { describe, it, expect, vi, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

vi.mock('../api.js', () => ({ api: { get: vi.fn(async () => ({ ok: false, items: [{ kind: 'pool_full', level: 'warning', subject: 'tank', open: 'storage' }] })) } }));

const { enablePhoneShell, onPhoneBack, openAlertsPage, setCompactBack } = await import('../components/phone-shell.js');
const { BREAKPOINTS } = await import('../device.js');
const tick = () => new Promise((r) => setTimeout(r, 40));
const STYLES = path.resolve(__dirname, '..', 'styles');

describe('UX-37: phones and tablets', () => {
  afterEach(() => {
    enablePhoneShell(false);
    setCompactBack(false);
  });

  it('the Alerts tab shows what needs attention, with the activity log one tap away', async () => {
    document.body.innerHTML = '';
    window.openManagementSection = vi.fn();
    enablePhoneShell(true);
    document.querySelector('[data-phone-tab="alerts"]').click();
    await tick();
    const page = document.getElementById('phone-alerts-page');
    expect(page.hidden).toBe(false);
    expect(page.querySelector('[data-ov-open="storage"]')).not.toBeNull();
    page.querySelector('[data-phone-log]').click();
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-events');
    page.querySelector('.phone-alerts-close').click();
    expect(page.hidden).toBe(true);
  });

  it('Back goes back a folder in Files before it leaves Files', async () => {
    document.body.innerHTML = '';
    enablePhoneShell(true);
    const fm = document.createElement('div');
    fm.className = 'file-manager-window';
    fm.style.zIndex = '1000';
    fm.innerHTML = '<button class="close-btn"></button>';
    let depth = 2;
    fm.zettBack = () => (depth > 0 ? (depth -= 1, true) : false);
    fm.querySelector('.close-btn').onclick = () => { fm.style.display = 'none'; };
    document.body.appendChild(fm);
    await tick();
    onPhoneBack();
    onPhoneBack();
    await tick();
    expect(depth).toBe(0);
    expect(fm.style.display).not.toBe('none');
    onPhoneBack();
    await tick();
    expect(fm.style.display).toBe('none');
  });

  it('between 601 and 768 px the browser Back closes a full-screen window too', async () => {
    document.body.innerHTML = '';
    const push = vi.spyOn(history, 'pushState');
    setCompactBack(true);
    const w = document.createElement('div');
    w.className = 'os-window';
    w.style.zIndex = '1000';
    w.innerHTML = '<button class="close-btn"></button>';
    w.querySelector('.close-btn').onclick = () => { w.style.display = 'none'; };
    document.body.appendChild(w);
    await tick();
    expect(push).toHaveBeenCalled();
    onPhoneBack();
    await tick();
    expect(w.style.display).toBe('none');
    expect(document.body.classList.contains('phone-page-open')).toBe(false); // no phone chrome here
  });

  it('every stylesheet uses the three widths', () => {
    const allowed = new Set(BREAKPOINTS.flatMap((b) => [b, b + 1]));
    const odd = [];
    for (const f of fs.readdirSync(STYLES).filter((n) => n.endsWith('.css'))) {
      const css = fs.readFileSync(path.join(STYLES, f), 'utf8');
      for (const m of css.matchAll(/@media[^{]*?\((?:max|min)-width:\s*(\d+)px\)/g)) {
        if (!allowed.has(Number(m[1]))) odd.push(`${f}: ${m[1]}px`);
      }
    }
    expect(odd).toEqual([]);
  });
});

describe('UX-36: small text only in the LCD replica', () => {
  it('the tablet sheet keeps 7-11 px text to #console-window', () => {
    const css = fs.readFileSync(path.join(STYLES, '24-tablet-bottom-sheet.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    const small = [...css.matchAll(/([^{}]+)\{[^{}]*font-size:\s*(\d+(?:\.\d+)?)px/g)].filter((m) => Number(m[2]) < 12);
    const outside = small.filter((m) => !m[1].includes('#console-window')).map((m) => m[1].trim());
    expect(small.length).toBeGreaterThan(0);
    expect(outside).toEqual([]);
  });
});
