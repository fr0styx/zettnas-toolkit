import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { state } from '../state.js';
import { exportThemeBundle, importThemeBundle } from '../components/settings.js';
import * as toastModule from '../toast.js';

const settle = () => new Promise((resolve) => setTimeout(resolve, 30));
const file = (obj) => new Blob([JSON.stringify(obj)], { type: 'application/json' });

describe('Theme files after the Kiboto rebrand', () => {
  beforeEach(() => {
    localStorage.clear();
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:theme');
    globalThis.URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  it('exports a .kiboto-theme.json named after the theme (lagoon when none is set)', () => {
    const names = [];
    const real = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = real(tag);
      if (tag === 'a') el.click = () => names.push(el.download);
      return el;
    });
    state.desktopTheme = '';
    exportThemeBundle();
    expect(names[0]).toMatch(/^kiboto-theme-lagoon-[0-9a-z]+\.kiboto-theme\.json$/);
  });

  it('imports new and old theme files and refuses anything else', async () => {
    const toast = vi.spyOn(toastModule, 'showToast').mockImplementation(() => {});
    importThemeBundle(file({ not_a_theme: 1 }));
    await settle();
    importThemeBundle(new Blob(['null'], { type: 'application/json' }));
    await settle();
    expect(toast.mock.calls.some(([msg]) => String(msg).includes('.kiboto-theme.json'))).toBe(true);
    toast.mockClear();
    importThemeBundle(file({ format: 'kiboto-theme', theme: 'emerald' }));
    await settle();
    importThemeBundle(file({ format: 'zett-theme', theme: 'amber' })); // saved before the rebrand
    await settle();
    importThemeBundle(file({ format: 'kiboto-theme' }));
    await settle();
    expect(toast.mock.calls.some(([msg]) => String(msg).includes('.kiboto-theme.json'))).toBe(false);
  });
});
