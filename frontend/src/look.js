/**
 * The person's look (APP-B): mode (dark, light or auto), one of five themes, the tint (0 = Subtle
 * … 1 = Strong), True black (dark mode only) and an optional own accent. It is kept with the
 * person's account, so it follows them to every device, and in this browser for a fast start.
 * Choices saved before APP-B (desktop_theme: cyber, sapphire, light, oled, …) are read and
 * translated, never overwritten, so an older cached page keeps working.
 */
import { api } from './api.js';

export const THEMES = ['lagoon', 'fjord', 'moss', 'heather', 'canyon'];
export const MODES = ['dark', 'light', 'auto'];
/** @typedef {{ mode: string, theme: string, tint: number, trueBlack: boolean, accent: string }} Look */

/** @type {Readonly<Look>} */
export const DEFAULT_LOOK = Object.freeze({ mode: 'dark', theme: 'lagoon', tint: 0, trueBlack: false, accent: '' });
/** How far the slider raises each theme's neutral colour (scripts/themes.py: TINT_MAX). */
const TINT_MAX = { lagoon: 3, fjord: 3, moss: 3, heather: 3, canyon: 2 };
/** The page colour per theme, for the phone's status bar (theme-color). */
const PAGE = {
  lagoon: ['#0a1113', '#f3f6f6'],
  fjord: ['#0b1016', '#f2f6fa'],
  moss: ['#0c110d', '#f2f7f3'],
  heather: ['#100e15', '#f6f4f9'],
  canyon: ['#130f09', '#fcf4ec'],
};
/** Each theme's main colour, dark and light (scripts/theme_palettes.json: primary). */
const PRIMARY = {
  lagoon: ['#33cdb8', '#0a7a70'],
  fjord: ['#64bdf8', '#0971a5'],
  moss: ['#98c275', '#52762f'],
  heather: ['#c69ef4', '#7a55a1'],
  canyon: ['#f39a66', '#9d522c'],
};
/** The colour a look's controls are drawn in: the person's own accent, else the theme's main colour. */
export function lookColour(look, dark = true) {
  const l = normalizeLook(look);
  return l.accent || PRIMARY[l.theme][dark ? 0 : 1];
}
/** Theme names saved before APP-B, and what they are now (scripts/theme_palettes.json: migration). */
const LEGACY = {
  cyber: { theme: 'lagoon' },
  amber: { theme: 'canyon' },
  crimson: { theme: 'canyon' },
  emerald: { theme: 'moss' },
  sapphire: { theme: 'fjord' },
  amethyst: { theme: 'heather' },
  light: { theme: 'lagoon', mode: 'light' },
  oled: { theme: 'lagoon', mode: 'dark', trueBlack: true },
  auto: { theme: 'lagoon', mode: 'auto' },
  system: { theme: 'lagoon', mode: 'auto' },
};
const LOOK_KEY = 'kiboto_look';
// a theme's stylesheet loads when it is chosen, not with the first page (first-load budget)
const SHEETS = {
  // @ts-ignore: a stylesheet has no types
  lagoon: () => import('./styles/themes/lagoon.css'),
  // @ts-ignore
  fjord: () => import('./styles/themes/fjord.css'),
  // @ts-ignore
  moss: () => import('./styles/themes/moss.css'),
  // @ts-ignore
  heather: () => import('./styles/themes/heather.css'),
  // @ts-ignore
  canyon: () => import('./styles/themes/canyon.css'),
};

/**
 * A look with every field present and valid; anything unknown falls back to the default.
 * @param {any} raw
 * @returns {Look}
 */
export function normalizeLook(raw) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const tint = Number(r.tint);
  const accent = typeof r.accent === 'string' && /^#[0-9a-f]{6}$/i.test(r.accent) ? r.accent.toLowerCase() : '';
  return {
    mode: MODES.includes(r.mode) ? r.mode : DEFAULT_LOOK.mode,
    theme: THEMES.includes(r.theme) ? r.theme : DEFAULT_LOOK.theme,
    tint: Number.isFinite(tint) ? Math.min(1, Math.max(0, Math.round(tint * 100) / 100)) : 0,
    trueBlack: r.trueBlack === true,
    accent,
  };
}

/**
 * A theme name saved before APP-B as a look (unknown names give the default).
 * @param {string} name
 * @param {Look} [base]
 * @returns {Look}
 */
export function fromLegacy(name, base = DEFAULT_LOOK) {
  return normalizeLook({ ...base, ...(LEGACY[name] || (THEMES.includes(name) ? { theme: name } : {})) });
}

function _storage() {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

/** Whether this browser holds a look saved since APP-B. */
export function hasOwnLook(storage = _storage()) {
  try {
    return Boolean(storage && storage.getItem(LOOK_KEY));
  } catch {
    return false;
  }
}

/** This browser's look: the saved one, else the pre-APP-B theme (and accent), else the default. */
export function loadLook(storage = _storage()) {
  try {
    const saved = storage && storage.getItem(LOOK_KEY);
    if (saved) return normalizeLook(JSON.parse(saved));
    const legacy = storage && storage.getItem('desktop_theme');
    const accent = (storage && storage.getItem('desktop_custom_accent')) || '';
    return normalizeLook({ ...fromLegacy(legacy && legacy !== 'yak' ? legacy : 'cyber'), accent });
  } catch {
    return { ...DEFAULT_LOOK };
  }
}

/** Keeps the look in this browser (the old desktop_theme key is left alone). */
export function storeLook(look, storage = _storage()) {
  try {
    storage?.setItem(LOOK_KEY, JSON.stringify(normalizeLook(look)));
  } catch {}
}

/** How strongly the neutrals are tinted: 1 at Subtle, up to the theme's maximum at Strong. */
export function tintFactor(look) {
  const l = normalizeLook(look);
  return Math.round((1 + l.tint * (TINT_MAX[l.theme] - 1)) * 100) / 100;
}

let _darkQuery = null;
let _applied = null;

function _prefersDark(win) {
  if (!win?.matchMedia) return true;
  if (!_darkQuery) {
    _darkQuery = win.matchMedia('(prefers-color-scheme: dark)');
    // Auto follows the device while the page is open
    _darkQuery.addEventListener?.('change', () => {
      if (_applied && _applied.look.mode === 'auto') applyLook(_applied.look, _applied.doc, win);
    });
  }
  return _darkQuery.matches;
}

/**
 * Puts the look on the page: the theme's class, light or dark, True black, the tint, the phone's
 * status-bar colour, and the theme's stylesheet when it is needed. Returns "dark" or "light".
 */
export function applyLook(look, doc = typeof document === 'undefined' ? null : document, win = typeof window === 'undefined' ? null : window) {
  const l = normalizeLook(look);
  const dark = l.mode === 'dark' || (l.mode === 'auto' && _prefersDark(win));
  _applied = { look: l, doc };
  const body = doc?.body;
  if (body) {
    for (const c of [...body.classList]) if (c.startsWith('kb-theme-')) body.classList.remove(c);
    body.classList.remove('theme-yak');
    body.classList.add(`kb-theme-${l.theme}`);
    body.classList.toggle('theme-light', !dark);
    body.classList.toggle('theme-oled', dark && l.trueBlack);
    body.classList.toggle('kb-tinted', l.tint > 0);
    if (l.tint > 0) body.style.setProperty('--kb-tint', String(tintFactor(l)));
    else body.style.removeProperty('--kb-tint');
    if (l.theme !== 'lagoon' || l.tint > 0) SHEETS[l.theme]().catch(() => null);
  }
  const meta = doc?.querySelector?.('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', PAGE[l.theme][dark ? 0 : 1]);
  return dark ? 'dark' : 'light';
}

/** Takes the look classes off the page (the hidden Yak theme draws on its own). */
export function clearLook(doc = typeof document === 'undefined' ? null : document) {
  const body = doc?.body;
  if (!body) return;
  for (const c of [...body.classList]) if (c.startsWith('kb-theme-')) body.classList.remove(c);
  body.classList.remove('kb-tinted', 'theme-light', 'theme-oled');
  body.style.removeProperty('--kb-tint');
}

let _saveTimer = null;
/** Saves the look on the person's account (a moment later, once the slider stops). Never throws. */
export function saveLookToAccount(look, delay = 400) {
  clearTimeout(_saveTimer);
  return new Promise((resolve) => {
    _saveTimer = setTimeout(() => {
      api.put('/api/auth/me/preferences', { look: normalizeLook(look) }).then(resolve, () => resolve(null));
    }, delay);
  });
}

/** The look saved on the person's account, or null when they have none yet. */
export function lookFromAccount(user) {
  const look = user?.preferences?.look;
  return look && typeof look === 'object' ? normalizeLook(look) : null;
}

export function _resetForTests() {
  _darkQuery = null;
  _applied = null;
  clearTimeout(_saveTimer);
}
