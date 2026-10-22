/**
 * ZettNAS Toolkit - Lightweight Internationalization (i18n) Engine
 * Supported Languages: English (en), Deutsch (de), 简体中文 (zh), Français (fr), Español (es).
 */

const STORAGE_KEY = 'zettnas_language';

export const SUPPORTED_LANGUAGES = [
  { code: 'en', name: 'English', flag: '🇺🇸' },
  { code: 'de', name: 'Deutsch', flag: '🇩🇪' },
  { code: 'zh', name: '简体中文', flag: '🇨🇳' },
  { code: 'fr', name: 'Français', flag: '🇫🇷' },
  { code: 'es', name: 'Español', flag: '🇪🇸' }
];

import en from './locales/en.js';

// Only English ships in the main bundle (it is the fallback). Each other language is its
// own file, loaded when that language is used (FE-03).
const LOADERS = {
  de: () => import('./locales/de.js'),
  zh: () => import('./locales/zh.js'),
  fr: () => import('./locales/fr.js'),
  es: () => import('./locales/es.js'),
};

// Languages loaded so far. English is always here.
export const TRANSLATIONS = { en };

const _loading = {};

/** Loads a language's strings (once). Resolves to false for unknown languages. */
export function loadLanguage(lang) {
  if (TRANSLATIONS[lang]) return Promise.resolve(true);
  if (!LOADERS[lang]) return Promise.resolve(false);
  if (!_loading[lang]) {
    _loading[lang] = LOADERS[lang]()
      .then((mod) => {
        TRANSLATIONS[lang] = mod.default;
        return true;
      })
      .catch((err) => {
        delete _loading[lang];
        console.warn(`[i18n] Could not load language '${lang}':`, err);
        return false;
      });
  }
  return _loading[lang];
}

export function isSupportedLanguage(lang) {
  return lang === 'en' || Boolean(LOADERS[lang]);
}

function _savedLanguage() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch (e) {
    return null;
  }
}

// Start fetching the saved language while the rest of the app loads.
(() => {
  const saved = _savedLanguage();
  if (saved && saved !== 'en' && LOADERS[saved]) loadLanguage(saved);
})();

let _currentLang = 'en';

export function getLanguage() {
  return _currentLang;
}

export function t(key, fallback = '', params = null) {
  let str;
  const dict = TRANSLATIONS[_currentLang] || TRANSLATIONS.en;
  if (dict && dict[key] != null) {
    str = dict[key];
  } else {
    const enDict = TRANSLATIONS.en;
    if (enDict && enDict[key] != null) {
      str = enDict[key];
    } else {
      str = fallback || key;
    }
  }

  if (params && typeof params === 'object') {
    for (const [pKey, pVal] of Object.entries(params)) {
      str = str.replace(new RegExp(`\\{${pKey}\\}`, 'g'), String(pVal));
    }
  }
  return str;
}

export async function setLanguage(lang) {
  if (!isSupportedLanguage(lang)) {
    lang = 'en';
  }
  if (!(await loadLanguage(lang))) {
    lang = 'en';
  }
  _currentLang = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch (e) {
    // Ignore localStorage write error
  }
  applyTranslations();
  syncLanguageSelectors();

  // Dispatch custom event for components that dynamically generate content
  window.dispatchEvent(new CustomEvent('zettnas:lang-changed', { detail: { lang } }));
}

export function applyTranslations() {
  // Elements with data-i18n: replace textContent
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    const key = el.getAttribute('data-i18n');
    if (key) {
      el.textContent = t(key, el.textContent);
    }
  });

  // Elements with data-i18n-title: replace title attribute
  document.querySelectorAll('[data-i18n-title]').forEach((el) => {
    const key = el.getAttribute('data-i18n-title');
    if (key) {
      el.setAttribute('title', t(key, el.getAttribute('title') || ''));
    }
  });

  // Elements with data-i18n-placeholder: replace placeholder
  document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
    const key = el.getAttribute('data-i18n-placeholder');
    if (key) {
      el.setAttribute('placeholder', t(key, el.getAttribute('placeholder') || ''));
    }
  });

  // Elements with data-i18n-aria-label: replace aria-label (FE-10)
  document.querySelectorAll('[data-i18n-aria-label]').forEach((el) => {
    const key = el.getAttribute('data-i18n-aria-label');
    if (key) {
      el.setAttribute('aria-label', t(key, el.getAttribute('aria-label') || ''));
    }
  });

  // Update HTML lang attribute
  if (document.documentElement) {
    document.documentElement.lang = _currentLang;
  }
}

function syncLanguageSelectors() {
  const selects = document.querySelectorAll('.language-picker-select');
  selects.forEach((sel) => {
    if (sel.value !== _currentLang) {
      sel.value = _currentLang;
    }
  });
}

export function initI18n() {
  let saved = null;
  try {
    saved = localStorage.getItem(STORAGE_KEY);
  } catch (e) {}

  if (!saved && typeof navigator !== 'undefined' && navigator.language) {
    const browserLang = navigator.language.split('-')[0].toLowerCase();
    if (isSupportedLanguage(browserLang)) {
      saved = browserLang;
    }
  }

  const ready = setLanguage(saved || 'en');

  // Bind change listener to all language selects
  document.querySelectorAll('.language-picker-select').forEach((sel) => {
    sel.addEventListener('change', (e) => {
      setLanguage(e.target.value);
    });
  });
  return ready;
}
