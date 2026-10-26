// UX-15: one definition of compact, phone and touch screens; touch-sized controls on any touch
// screen; the phone launcher opens with how the server is doing.
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

const ROUTES = vi.hoisted(() => ({ storage: vi.fn(), files: vi.fn() }));
vi.mock('../router.js', () => ({ ROUTES }));
vi.mock('../api.js', () => {
  const api = { get: vi.fn(), post: vi.fn() };
  return { api, default: api };
});

import { api } from '../api.js';
import { COMPACT_MAX, isCompact, isTouch } from '../device.js';
import { enablePhoneShell, refreshHealth } from '../components/phone-shell.js';

const setWidth = (w) => Object.defineProperty(window, 'innerWidth', { value: w, configurable: true });
const settle = () => new Promise((r) => setTimeout(r, 0));

describe('one definition of each kind of screen', () => {
  afterEach(() => {
    document.body.className = '';
    setWidth(1024);
  });

  it('compact: narrow windows, the phone shell, or mobile mode chosen in the dock', () => {
    setWidth(1024);
    expect(isCompact()).toBe(false);
    setWidth(COMPACT_MAX);
    expect(isCompact()).toBe(true);
    setWidth(1024);
    document.body.classList.add('mobile-mode');
    expect(isCompact()).toBe(true);
    document.body.className = 'phone-shell';
    expect(isCompact()).toBe(true);
  });

  it('touch follows the pointer, not the width', () => {
    const had = window.matchMedia;
    window.matchMedia = (q) => ({ matches: q === '(pointer: coarse)', addEventListener() {} });
    setWidth(820); // a portrait tablet: not compact, but touch
    expect(isCompact()).toBe(false);
    expect(isTouch()).toBe(true);
    window.matchMedia = had;
  });

  it('every control is finger-sized on a touch screen', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '..', 'styles', '61-touch.css'), 'utf8');
    const block = css.slice(css.indexOf('@media (pointer: coarse)'));
    expect(block).toMatch(/button,[\s\S]*min-height: 44px/);
    expect(block).toMatch(/\.win-btn::after[\s\S]*inset:/);
    expect(fs.readFileSync(path.resolve(__dirname, '..', 'style.css'), 'utf8')).toContain("styles/61-touch.css");
  });
});

describe('the phone launcher leads with health', () => {
  afterEach(() => {
    enablePhoneShell(false);
    vi.clearAllMocks();
  });

  it('shows "Everything is fine" when nothing needs attention', async () => {
    api.get.mockResolvedValue({ ok: true, items: [] });
    enablePhoneShell(true);
    await settle();
    const box = document.querySelector('#phone-shell .phone-health');
    expect(box.hidden).toBe(false);
    expect(box.textContent).toContain('Everything is fine');
    // it comes before the numbers and the tiles
    const launcher = document.getElementById('phone-launcher');
    expect(launcher.firstElementChild).toBe(box);
  });

  it('lists what needs attention, and Open goes there', async () => {
    api.get.mockResolvedValue({ ok: false, items: [{ kind: 'storage_full', level: 'warning', subject: '93%', open: 'storage' }] });
    enablePhoneShell(true);
    await settle();
    const box = document.querySelector('#phone-shell .phone-health');
    expect(box.textContent).toContain('Storage is 93% full.');
    box.querySelector('[data-ov-open="storage"]').click();
    expect(ROUTES.storage).toHaveBeenCalledTimes(1);
  });

  it('hides the card when the summary cannot be read, and asks again at most once a minute', async () => {
    api.get.mockRejectedValue(new Error('403'));
    enablePhoneShell(true);
    await settle();
    expect(document.querySelector('#phone-shell .phone-health').hidden).toBe(true);
    const calls = api.get.mock.calls.length;
    await refreshHealth();
    expect(api.get.mock.calls.length).toBe(calls);
    await refreshHealth(true);
    expect(api.get.mock.calls.length).toBe(calls + 1);
  });
});
