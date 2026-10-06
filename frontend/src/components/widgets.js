import { ZettEventBus } from '../event-bus.js';
import { state } from '../state.js';
import { showToast } from '../toast.js';

const STORAGE_KEY = 'zettnas_widgets_config';
const WEATHER_CACHE_KEY = 'zettnas_weather_cache';

const DEFAULT_CONFIG = {
  enabled: true,
  position: 'pos-top-right',
  opacity: 'glass-standard',
  scale: 'scale-normal',
  order: ['clock', 'weather', 'calendar', 'system', 'network', 'storage', 'uptime'],
  widgets: {
    clock: true,
    calendar: false,
    weather: true,
    system: true,
    network: true,
    storage: true,
    uptime: false,
  },
  clockFormat: '24',
  weatherCity: '',
  weatherLat: null,
  weatherLon: null,
  weatherCountry: '',
  weatherUnit: 'c',
  calendarCountry: 'auto',
  calendarHolidays: true,
};

let _config = null;
let _clockInterval = null;
let _weatherInterval = null;
let _calViewDate = new Date();
let _geoDebounceTimer = null;
let _currentSuggestions = [];
let _activeSuggestionIndex = -1;
let _holidayData = {};
let _currentHoverHoliday = null;

function formatSpeed(bytesPerSec) {
  if (bytesPerSec === 0 || isNaN(bytesPerSec)) return '0 B/s';
  const k = 1024;
  const sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
  const i = Math.floor(Math.log(bytesPerSec) / Math.log(k));
  if (i < 0) return '0 B/s';
  return parseFloat((bytesPerSec / Math.pow(k, i)).toFixed(1)) + ' ' + (sizes[i] || 'B/s');
}

export function loadWidgetConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      _config = Object.assign({}, DEFAULT_CONFIG, parsed);
      _config.widgets = Object.assign({}, DEFAULT_CONFIG.widgets, parsed.widgets || {});
      if (Array.isArray(parsed.order) && parsed.order.length) {
        _config.order = parsed.order.slice();
        DEFAULT_CONFIG.order.forEach((id) => {
          if (!_config.order.includes(id)) _config.order.push(id);
        });
      } else {
        _config.order = [...DEFAULT_CONFIG.order];
      }
      return _config;
    }
  } catch (e) {
    console.warn('Failed to load widget config:', e);
  }
  _config = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
  return _config;
}

export function saveWidgetConfig(newConfig) {
  _config = Object.assign({}, _config || DEFAULT_CONFIG, newConfig);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(_config));
  } catch (e) {
    console.warn('Failed to persist widget config:', e);
  }
  applyWidgetConfig();
  syncWidgetSettingsUI();
  return _config;
}

export function applyWidgetConfig() {
  const container = document.getElementById('desktop-widgets-container');
  if (!container) return;

  const config = _config || loadWidgetConfig();

  // Master visibility
  container.style.display = config.enabled ? 'flex' : 'none';

  // Position
  container.classList.remove('pos-top-right', 'pos-top-left', 'pos-bottom-right', 'pos-bottom-left');
  container.classList.add(config.position || 'pos-top-right');

  // Opacity / Glass
  container.classList.remove('glass-subtle', 'glass-standard', 'glass-solid');
  container.classList.add(config.opacity || 'glass-standard');

  // Scale
  container.classList.remove('scale-compact', 'scale-normal', 'scale-large');
  container.classList.add(config.scale || 'scale-normal');

  // Sub-widgets visibility
  const wClock = document.getElementById('widget-clock');
  const wCalendar = document.getElementById('widget-calendar');
  const wWeather = document.getElementById('widget-weather');
  const wSystem = document.getElementById('widget-system');
  const wNetwork = document.getElementById('widget-network');
  const wStorage = document.getElementById('widget-storage');
  const wUptime = document.getElementById('widget-uptime');

  if (wClock) wClock.style.display = config.widgets.clock ? 'block' : 'none';
  if (wCalendar) wCalendar.style.display = config.widgets.calendar ? 'block' : 'none';
  if (wWeather) wWeather.style.display = config.widgets.weather ? 'block' : 'none';
  if (wSystem) wSystem.style.display = config.widgets.system ? 'block' : 'none';
  if (wNetwork) wNetwork.style.display = config.widgets.network ? 'block' : 'none';
  if (wStorage) wStorage.style.display = config.widgets.storage ? 'block' : 'none';
  if (wUptime) wUptime.style.display = config.widgets.uptime ? 'block' : 'none';

  // Reorganize desktop widgets in the EXACT same order on the desktop
  const order = Array.isArray(config.order) && config.order.length ? config.order : DEFAULT_CONFIG.order;
  order.forEach((id) => {
    const el = document.getElementById(`widget-${id}`);
    if (el && container.contains(el)) {
      container.appendChild(el);
    }
  });

  if (config.widgets.clock) updateClock();
  if (config.widgets.calendar) renderCalendar();
  if (config.widgets.weather) fetchWeather();
}

export function syncWidgetSettingsUI() {
  const config = _config || loadWidgetConfig();

  const toggleMaster = document.getElementById('widget-toggle-master');
  const posSelect = document.getElementById('widget-pos-select');
  const opacitySelect = document.getElementById('widget-opacity-select');
  const scaleSelect = document.getElementById('widget-scale-select');

  const chkClock = document.getElementById('w-cfg-clock');
  const chkCalendar = document.getElementById('w-cfg-calendar');
  const chkWeather = document.getElementById('w-cfg-weather');
  const chkSystem = document.getElementById('w-cfg-system');
  const chkNetwork = document.getElementById('w-cfg-network');
  const chkStorage = document.getElementById('w-cfg-storage');
  const chkUptime = document.getElementById('w-cfg-uptime');

  const weatherCityInput = document.getElementById('widget-weather-city-input');
  const weatherUnitSelect = document.getElementById('widget-weather-unit-select');

  if (toggleMaster) toggleMaster.checked = !!config.enabled;
  if (posSelect) posSelect.value = config.position || 'pos-top-right';
  if (opacitySelect) opacitySelect.value = config.opacity || 'glass-standard';
  if (scaleSelect) scaleSelect.value = config.scale || 'scale-normal';

  if (chkClock) chkClock.checked = !!config.widgets.clock;
  if (chkCalendar) chkCalendar.checked = !!config.widgets.calendar;
  if (chkWeather) chkWeather.checked = !!config.widgets.weather;
  if (chkSystem) chkSystem.checked = !!config.widgets.system;
  if (chkNetwork) chkNetwork.checked = !!config.widgets.network;
  if (chkStorage) chkStorage.checked = !!config.widgets.storage;
  if (chkUptime) chkUptime.checked = !!config.widgets.uptime;

  if (weatherCityInput && document.activeElement !== weatherCityInput) {
    weatherCityInput.value = config.weatherCity || '';
  }
  if (weatherUnitSelect) weatherUnitSelect.value = config.weatherUnit || 'c';

  const calCountrySelect = document.getElementById('widget-calendar-country-select');
  const calHolidayToggle = document.getElementById('w-cfg-holiday-toggle');
  if (calCountrySelect) calCountrySelect.value = config.calendarCountry || 'auto';
  if (calHolidayToggle) calHolidayToggle.checked = config.calendarHolidays !== false;

  // Reorder sortable list items in the Settings UI to match config.order
  const list = document.getElementById('widget-sortable-list');
  if (list && config.order) {
    config.order.forEach((id) => {
      const item = list.querySelector(`.widget-sortable-item[data-widget-id="${id}"]`);
      if (item && list.contains(item)) {
        list.appendChild(item);
      }
    });
  }
}

/* =========================================================================
   Clock Widget Logic
   ========================================================================= */
export function updateClock() {
  const clockWidget = document.getElementById('widget-clock');
  if (!clockWidget || clockWidget.style.display === 'none') return;

  const now = new Date();
  const format = _config?.clockFormat || state.clockFormat || '24';

  const timeEl = document.getElementById('w-clock-time');
  const secEl = document.getElementById('w-clock-sec');
  const ampmEl = document.getElementById('w-clock-ampm');
  const dateEl = document.getElementById('w-clock-date');
  const tzBadge = document.getElementById('w-clock-tz');

  let hours = now.getHours();
  const minutes = String(now.getMinutes()).padStart(2, '0');
  const seconds = String(now.getSeconds()).padStart(2, '0');
  let ampm = '';

  if (format === '12') {
    ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12 || 12;
  }
  const hoursStr = format === '12' ? String(hours) : String(hours).padStart(2, '0');

  if (timeEl && timeEl.childNodes[0]) {
    timeEl.childNodes[0].nodeValue = `${hoursStr}:${minutes}`;
  }
  if (secEl) {
    secEl.textContent = `:${seconds}`;
  }
  if (ampmEl) {
    ampmEl.textContent = ampm;
  }
  if (dateEl) {
    try {
      const dateStr = new Intl.DateTimeFormat([], {
        weekday: 'long',
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      }).format(now);
      dateEl.textContent = dateStr;
    } catch (e) {
      dateEl.textContent = now.toDateString();
    }
  }
  if (tzBadge) {
    tzBadge.textContent = format === '12' ? '12H' : '24H';
  }
}

/* =========================================================================
   Calendar & Official Holidays Logic
   ========================================================================= */
const COUNTRY_NAMES = {
  US: 'United States',
  GB: 'United Kingdom',
  DE: 'Germany',
  FR: 'France',
  ES: 'Spain',
  IT: 'Italy',
  CA: 'Canada',
  AU: 'Australia',
  JP: 'Japan',
  CN: 'China',
  CH: 'Switzerland',
  AT: 'Austria',
  NL: 'Netherlands',
  SE: 'Sweden',
  NO: 'Norway',
  DK: 'Denmark',
  PL: 'Poland',
  BR: 'Brazil',
  MX: 'Mexico',
  IN: 'India',
};

const HOLIDAY_CACHE_PREFIX = 'zettnas_holidays_';

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function getActiveCountry() {
  const cfg = _config || loadWidgetConfig();
  if (cfg.calendarCountry && cfg.calendarCountry !== 'auto') {
    return cfg.calendarCountry.toUpperCase();
  }
  // Try weatherCountry if set (e.g. user selected New York -> "US")
  if (cfg.weatherCountry && cfg.weatherCountry.trim()) {
    const wc = cfg.weatherCountry.trim().toUpperCase();
    if (wc.length === 2) return wc;
  }
  // Try navigator locale
  try {
    const lang = (navigator.language || navigator.userLanguage || '').toUpperCase();
    if (lang.includes('-')) {
      const parts = lang.split('-');
      if (parts[1] && parts[1].length === 2) return parts[1];
    }
  } catch (e) {}
  // Try timezone
  try {
    const tz = (Intl.DateTimeFormat().resolvedOptions().timeZone || '').toUpperCase();
    if (tz.startsWith('AMERICA/NEW_YORK') || tz.startsWith('AMERICA/CHICAGO') || tz.startsWith('AMERICA/LOS_ANGELES') || tz.startsWith('AMERICA/DENVER') || tz.startsWith('AMERICA/PHOENIX')) return 'US';
    if (tz.startsWith('AMERICA/TORONTO') || tz.startsWith('AMERICA/VANCOUVER') || tz.startsWith('AMERICA/MONTREAL')) return 'CA';
    if (tz.startsWith('EUROPE/BERLIN')) return 'DE';
    if (tz.startsWith('EUROPE/LONDON')) return 'GB';
    if (tz.startsWith('EUROPE/PARIS')) return 'FR';
    if (tz.startsWith('EUROPE/MADRID')) return 'ES';
    if (tz.startsWith('EUROPE/ROME')) return 'IT';
    if (tz.startsWith('EUROPE/ZURICH')) return 'CH';
    if (tz.startsWith('EUROPE/VIENNA')) return 'AT';
    if (tz.startsWith('EUROPE/AMSTERDAM')) return 'NL';
    if (tz.startsWith('ASIA/SHANGHAI') || tz.startsWith('ASIA/CHONGQING')) return 'CN';
    if (tz.startsWith('ASIA/TOKYO')) return 'JP';
    if (tz.startsWith('AUSTRALIA/')) return 'AU';
    if (tz.startsWith('AMERICA/SAO_PAULO')) return 'BR';
    if (tz.startsWith('AMERICA/MEXICO_CITY')) return 'MX';
  } catch (e) {}
  return 'US';
}

function getEasterSunday(year) {
  const a = year % 19;
  const b = Math.floor(year / 100);
  const c = year % 100;
  const d = Math.floor(b / 4);
  const e = b % 4;
  const f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4);
  const k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31) - 1;
  const day = ((h + l - 7 * m + 114) % 31) + 1;
  return new Date(year, month, day);
}

function addDays(date, days) {
  const res = new Date(date);
  res.setDate(res.getDate() + days);
  return res;
}

function getNthWeekdayOfMonth(year, month, dayOfWeek, n) {
  const firstDay = new Date(year, month, 1);
  let day = 1 + ((dayOfWeek - firstDay.getDay() + 7) % 7);
  day += (n - 1) * 7;
  return new Date(year, month, day);
}

function getLastWeekdayOfMonth(year, month, dayOfWeek) {
  const lastDay = new Date(year, month + 1, 0);
  const diff = (lastDay.getDay() - dayOfWeek + 7) % 7;
  return new Date(year, month, lastDay.getDate() - diff);
}

function toDateKey(year, month, day) {
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

function addHolidayEntry(map, date, name, localName) {
  const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  if (!map[key]) map[key] = [];
  map[key].push({ name, localName: localName || name });
}

function getBuiltInHolidays(year, countryCode) {
  const map = {};
  const easter = getEasterSunday(year);

  if (countryCode === 'US') {
    addHolidayEntry(map, new Date(year, 0, 1), "New Year's Day");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 0, 1, 3), "Martin Luther King, Jr. Day");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 1, 1, 3), "Washington's Birthday (Presidents' Day)");
    addHolidayEntry(map, getLastWeekdayOfMonth(year, 4, 1), "Memorial Day");
    addHolidayEntry(map, new Date(year, 5, 19), "Juneteenth National Independence Day");
    addHolidayEntry(map, new Date(year, 6, 4), "Independence Day");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 8, 1, 1), "Labor Day");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 9, 1, 2), "Columbus Day / Indigenous Peoples' Day");
    addHolidayEntry(map, new Date(year, 10, 11), "Veterans Day");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 10, 4, 4), "Thanksgiving Day");
    addHolidayEntry(map, new Date(year, 11, 25), "Christmas Day");
  } else if (countryCode === 'DE') {
    addHolidayEntry(map, new Date(year, 0, 1), "New Year's Day", "Neujahr");
    addHolidayEntry(map, addDays(easter, -2), "Good Friday", "Karfreitag");
    addHolidayEntry(map, addDays(easter, 1), "Easter Monday", "Ostermontag");
    addHolidayEntry(map, new Date(year, 4, 1), "Labor Day", "Tag der Arbeit");
    addHolidayEntry(map, addDays(easter, 39), "Ascension Day", "Christi Himmelfahrt");
    addHolidayEntry(map, addDays(easter, 50), "Whit Monday", "Pfingstmontag");
    addHolidayEntry(map, new Date(year, 9, 3), "German Unity Day", "Tag der Deutschen Einheit");
    addHolidayEntry(map, new Date(year, 11, 25), "Christmas Day", "1. Weihnachtstag");
    addHolidayEntry(map, new Date(year, 11, 26), "St. Stephen's Day", "2. Weihnachtstag");
  } else if (countryCode === 'GB') {
    addHolidayEntry(map, new Date(year, 0, 1), "New Year's Day");
    addHolidayEntry(map, addDays(easter, -2), "Good Friday");
    addHolidayEntry(map, addDays(easter, 1), "Easter Monday");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 4, 1, 1), "Early May Bank Holiday");
    addHolidayEntry(map, getLastWeekdayOfMonth(year, 4, 1), "Spring Bank Holiday");
    addHolidayEntry(map, getLastWeekdayOfMonth(year, 7, 1), "Summer Bank Holiday");
    addHolidayEntry(map, new Date(year, 11, 25), "Christmas Day");
    addHolidayEntry(map, new Date(year, 11, 26), "Boxing Day");
  } else if (countryCode === 'FR') {
    addHolidayEntry(map, new Date(year, 0, 1), "New Year's Day", "Jour de l'An");
    addHolidayEntry(map, addDays(easter, 1), "Easter Monday", "Lundi de Pâques");
    addHolidayEntry(map, new Date(year, 4, 1), "Labour Day", "Fête du Travail");
    addHolidayEntry(map, new Date(year, 4, 8), "Victory in Europe Day", "Victoire 1945");
    addHolidayEntry(map, addDays(easter, 39), "Ascension Day", "Ascension");
    addHolidayEntry(map, addDays(easter, 50), "Whit Monday", "Lundi de Pentecôte");
    addHolidayEntry(map, new Date(year, 6, 14), "Bastille Day", "Fête Nationale");
    addHolidayEntry(map, new Date(year, 7, 15), "Assumption Day", "Assomption");
    addHolidayEntry(map, new Date(year, 10, 1), "All Saints' Day", "La Toussaint");
    addHolidayEntry(map, new Date(year, 10, 11), "Armistice Day", "Armistice 1918");
    addHolidayEntry(map, new Date(year, 11, 25), "Christmas Day", "Noël");
  } else if (countryCode === 'ES') {
    addHolidayEntry(map, new Date(year, 0, 1), "New Year's Day", "Año Nuevo");
    addHolidayEntry(map, new Date(year, 0, 6), "Epiphany", "Día de Reyes");
    addHolidayEntry(map, addDays(easter, -2), "Good Friday", "Viernes Santo");
    addHolidayEntry(map, new Date(year, 4, 1), "Labour Day", "Fiesta del Trabajo");
    addHolidayEntry(map, new Date(year, 7, 15), "Assumption of Mary", "Asunción de la Virgen");
    addHolidayEntry(map, new Date(year, 9, 12), "National Day of Spain", "Fiesta Nacional de España");
    addHolidayEntry(map, new Date(year, 10, 1), "All Saints' Day", "Todos los Santos");
    addHolidayEntry(map, new Date(year, 11, 6), "Constitution Day", "Día de la Constitución");
    addHolidayEntry(map, new Date(year, 11, 8), "Immaculate Conception", "Inmaculada Concepción");
    addHolidayEntry(map, new Date(year, 11, 25), "Christmas Day", "Navidad");
  } else if (countryCode === 'CA') {
    addHolidayEntry(map, new Date(year, 0, 1), "New Year's Day");
    addHolidayEntry(map, addDays(easter, -2), "Good Friday");
    const vDay = new Date(year, 4, 24 - ((new Date(year, 4, 24).getDay() - 1 + 7) % 7));
    addHolidayEntry(map, vDay, "Victoria Day");
    addHolidayEntry(map, new Date(year, 6, 1), "Canada Day");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 8, 1, 1), "Labour Day");
    addHolidayEntry(map, new Date(year, 8, 30), "Truth and Reconciliation Day");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 9, 1, 2), "Thanksgiving Day");
    addHolidayEntry(map, new Date(year, 10, 11), "Remembrance Day");
    addHolidayEntry(map, new Date(year, 11, 25), "Christmas Day");
    addHolidayEntry(map, new Date(year, 11, 26), "Boxing Day");
  } else if (countryCode === 'AU') {
    addHolidayEntry(map, new Date(year, 0, 1), "New Year's Day");
    addHolidayEntry(map, new Date(year, 0, 26), "Australia Day");
    addHolidayEntry(map, addDays(easter, -2), "Good Friday");
    addHolidayEntry(map, addDays(easter, 1), "Easter Monday");
    addHolidayEntry(map, new Date(year, 3, 25), "ANZAC Day");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 5, 1, 2), "King's Birthday");
    addHolidayEntry(map, new Date(year, 11, 25), "Christmas Day");
    addHolidayEntry(map, new Date(year, 11, 26), "Boxing Day");
  } else if (countryCode === 'JP') {
    addHolidayEntry(map, new Date(year, 0, 1), "New Year's Day", "元日");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 0, 1, 2), "Coming of Age Day", "成人の日");
    addHolidayEntry(map, new Date(year, 1, 11), "National Foundation Day", "建国記念の日");
    addHolidayEntry(map, new Date(year, 1, 23), "Emperor's Birthday", "天皇誕生日");
    addHolidayEntry(map, new Date(year, 2, 20), "Vernal Equinox Day", "春分の日");
    addHolidayEntry(map, new Date(year, 3, 29), "Showa Day", "昭和の日");
    addHolidayEntry(map, new Date(year, 4, 3), "Constitution Memorial Day", "憲法記念日");
    addHolidayEntry(map, new Date(year, 4, 4), "Greenery Day", "みどりの日");
    addHolidayEntry(map, new Date(year, 4, 5), "Children's Day", "こどもの日");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 6, 1, 3), "Marine Day", "海の日");
    addHolidayEntry(map, new Date(year, 7, 11), "Mountain Day", "山の日");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 8, 1, 3), "Respect for the Aged Day", "敬老の日");
    addHolidayEntry(map, new Date(year, 8, 23), "Autumnal Equinox Day", "秋分の日");
    addHolidayEntry(map, getNthWeekdayOfMonth(year, 9, 1, 2), "Sports Day", "スポーツの日");
    addHolidayEntry(map, new Date(year, 10, 3), "Culture Day", "文化の日");
    addHolidayEntry(map, new Date(year, 10, 23), "Labor Thanksgiving Day", "勤労感謝の日");
  } else if (countryCode === 'CN') {
    addHolidayEntry(map, new Date(year, 0, 1), "New Year's Day", "元旦");
    addHolidayEntry(map, new Date(year, 3, 4), "Tomb Sweeping Day", "清明节");
    addHolidayEntry(map, new Date(year, 4, 1), "Labour Day", "劳动节");
    addHolidayEntry(map, new Date(year, 9, 1), "National Day", "国庆节");
    addHolidayEntry(map, new Date(year, 9, 2), "National Day (Golden Week)", "国庆节");
    addHolidayEntry(map, new Date(year, 9, 3), "National Day (Golden Week)", "国庆节");
  } else {
    addHolidayEntry(map, new Date(year, 0, 1), "New Year's Day");
    addHolidayEntry(map, addDays(easter, -2), "Good Friday");
    addHolidayEntry(map, addDays(easter, 1), "Easter Monday");
    addHolidayEntry(map, new Date(year, 4, 1), "International Workers' Day");
    addHolidayEntry(map, new Date(year, 11, 25), "Christmas Day");
  }
  return map;
}

async function fetchOnlineHolidays(year, countryCode) {
  const cacheKey = `${HOLIDAY_CACHE_PREFIX}${countryCode}_${year}`;
  try {
    const res = await fetch(`https://date.nager.at/api/v3/PublicHolidays/${year}/${countryCode}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const items = await res.json();
    if (Array.isArray(items) && items.length) {
      const holidayMap = {};
      items.forEach((item) => {
        if (!item.date) return;
        if (!holidayMap[item.date]) holidayMap[item.date] = [];
        holidayMap[item.date].push({
          name: item.name,
          localName: item.localName || item.name,
        });
      });
      _holidayData[`${countryCode}_${year}`] = holidayMap;
      try {
        localStorage.setItem(cacheKey, JSON.stringify(holidayMap));
      } catch (e) {}

      if (_calViewDate.getFullYear() === year) {
        renderCalendar();
      }
      return holidayMap;
    }
  } catch (err) {
    // Graceful offline fallback
  }
  return null;
}

function getHolidaysForYear(year, countryCode) {
  const key = `${countryCode}_${year}`;
  if (_holidayData[key]) {
    return _holidayData[key];
  }
  try {
    const cached = localStorage.getItem(`${HOLIDAY_CACHE_PREFIX}${countryCode}_${year}`);
    if (cached) {
      const parsed = JSON.parse(cached);
      if (parsed && typeof parsed === 'object') {
        _holidayData[key] = parsed;
        return parsed;
      }
    }
  } catch (e) {}

  const builtIn = getBuiltInHolidays(year, countryCode);
  _holidayData[key] = builtIn;

  fetchOnlineHolidays(year, countryCode);

  return builtIn;
}

function showCalendarTooltip(targetEl, name, dateStr) {
  _currentHoverHoliday = { name, dateStr };
  let tooltip = document.getElementById('cal-holiday-tooltip');
  if (!tooltip) {
    tooltip = document.createElement('div');
    tooltip.id = 'cal-holiday-tooltip';
    tooltip.className = 'cal-holiday-tooltip';
    document.body.appendChild(tooltip);
  }

  const country = getActiveCountry();

  tooltip.innerHTML = `
    <span class="cal-holiday-tooltip-icon">🎉</span>
    <div>
      <div class="cal-holiday-tooltip-name">${escapeHtml(name)}</div>
      <div class="cal-holiday-tooltip-sub">${dateStr ? escapeHtml(dateStr) + ' • ' : ''}Official Holiday (${country})</div>
    </div>
  `;
  tooltip.style.display = 'flex';

  const rect = targetEl.getBoundingClientRect();
  const tooltipRect = tooltip.getBoundingClientRect();

  const halfW = (tooltipRect.width || 170) / 2;
  let left = rect.left + rect.width / 2;
  left = Math.max(halfW + 10, Math.min(window.innerWidth - halfW - 10, left));

  let top = rect.top - 8;
  let isBelow = false;
  if (top - (tooltipRect.height || 42) < 10) {
    top = rect.bottom + 8;
    isBelow = true;
  }

  tooltip.classList.toggle('pos-below', isBelow);
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;

  requestAnimationFrame(() => {
    tooltip.classList.add('visible');
  });

  const glanceBar = document.getElementById('w-cal-glance-bar');
  if (glanceBar) {
    glanceBar.className = 'cal-glance-bar';
    glanceBar.innerHTML = `<span class="cal-glance-bar-icon">🎉</span> <span><strong>${escapeHtml(dateStr || '')}:</strong> ${escapeHtml(name)}</span>`;
  }
}

function hideCalendarTooltip() {
  _currentHoverHoliday = null;
  const tooltip = document.getElementById('cal-holiday-tooltip');
  if (tooltip) {
    tooltip.classList.remove('visible');
    setTimeout(() => {
      if (!tooltip.classList.contains('visible')) {
        tooltip.style.display = 'none';
      }
    }, 150);
  }
  renderGlanceBarForCurrentView();
}

function renderGlanceBarForCurrentView() {
  const glanceBar = document.getElementById('w-cal-glance-bar');
  if (!glanceBar) return;

  const year = _calViewDate.getFullYear();
  const month = _calViewDate.getMonth();
  const today = new Date();
  const country = getActiveCountry();
  const config = _config || loadWidgetConfig();

  if (config.calendarHolidays === false) {
    glanceBar.style.display = 'none';
    return;
  }
  glanceBar.style.display = 'flex';

  const holidaysYear = getHolidaysForYear(year, country);
  const totalDays = new Date(year, month + 1, 0).getDate();
  const monthHolidays = [];

  for (let d = 1; d <= totalDays; d++) {
    const key = toDateKey(year, month, d);
    const holidayList = holidaysYear[key];
    if (holidayList && holidayList.length > 0) {
      const name = holidayList.map((h) => h.name || h.localName).filter((v, idx, arr) => arr.indexOf(v) === idx).join(' / ');
      const dateStr = `${new Intl.DateTimeFormat('en-US', { month: 'short' }).format(new Date(year, month, d))} ${d}`;
      monthHolidays.push({ day: d, name, dateStr });
    }
  }

  if (!monthHolidays.length) {
    glanceBar.className = 'cal-glance-bar empty';
    glanceBar.innerHTML = '<span>No official holidays this month</span>';
    return;
  }

  let target = null;
  const isCurrentMonth = today.getFullYear() === year && today.getMonth() === month;
  if (isCurrentMonth) {
    target = monthHolidays.find((h) => h.day >= today.getDate());
  }
  if (!target) {
    target = monthHolidays[0];
  }

  glanceBar.className = 'cal-glance-bar';
  glanceBar.innerHTML = `<span class="cal-glance-bar-icon">✨</span> <span>${escapeHtml(target.dateStr)}: ${escapeHtml(target.name)}</span>`;
  glanceBar.title = `${target.dateStr}: ${target.name} (Official Holiday)`;
}

export function renderCalendar() {
  const calWidget = document.getElementById('widget-calendar');
  if (!calWidget || calWidget.style.display === 'none') return;

  const grid = document.getElementById('w-calendar-grid');
  const monthBadge = document.getElementById('w-cal-month');
  const countryBadge = document.getElementById('w-cal-country-badge');
  if (!grid) return;

  const config = _config || loadWidgetConfig();
  const year = _calViewDate.getFullYear();
  const month = _calViewDate.getMonth();
  const today = new Date();

  const country = getActiveCountry();
  const countryFullName = COUNTRY_NAMES[country] || country;

  if (countryBadge) {
    countryBadge.textContent = country;
    countryBadge.title = `Official holidays: ${countryFullName} (${country}) - Click to configure`;
  }

  if (monthBadge) {
    const monthNames = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
    monthBadge.textContent = `${monthNames[month]} ${year}`;
  }

  const holidaysEnabled = config.calendarHolidays !== false;
  const holidaysYear = holidaysEnabled ? getHolidaysForYear(year, country) : {};

  const prevMonthDate = new Date(year, month - 1, 1);
  const prevYear = prevMonthDate.getFullYear();
  const prevMonthIdx = prevMonthDate.getMonth();
  const prevHolidaysYear = holidaysEnabled && prevYear !== year ? getHolidaysForYear(prevYear, country) : holidaysYear;

  const nextMonthDate = new Date(year, month + 1, 1);
  const nextYear = nextMonthDate.getFullYear();
  const nextMonthIdx = nextMonthDate.getMonth();
  const nextHolidaysYear = holidaysEnabled && nextYear !== year ? getHolidaysForYear(nextYear, country) : holidaysYear;

  const firstDay = new Date(year, month, 1).getDay(); // 0 is Sun
  const totalDays = new Date(year, month + 1, 0).getDate();
  const prevMonthTotalDays = new Date(year, month, 0).getDate();

  let html = '';
  const weekdays = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
  weekdays.forEach((d) => {
    html += `<div class="cal-weekday">${d}</div>`;
  });

  // Previous month padding
  for (let i = firstDay - 1; i >= 0; i--) {
    const d = prevMonthTotalDays - i;
    const key = toDateKey(prevYear, prevMonthIdx, d);
    const holidayList = prevHolidaysYear[key];
    const isHoliday = !!holidayList && holidayList.length > 0;
    const holidayName = isHoliday ? holidayList.map((h) => h.name || h.localName).filter((v, idx, arr) => arr.indexOf(v) === idx).join(' / ') : '';
    const dateStr = `${new Intl.DateTimeFormat('en-US', { month: 'short' }).format(new Date(prevYear, prevMonthIdx, d))} ${d}`;
    html += `<div class="cal-day cal-other-month${isHoliday ? ' cal-holiday' : ''}" data-day="${d}" ${isHoliday ? `data-holiday="${escapeHtml(holidayName)}" data-date-str="${dateStr}" title="${escapeHtml(holidayName)}"` : ''}>${d}</div>`;
  }

  // Current month days
  for (let d = 1; d <= totalDays; d++) {
    const isToday =
      today.getFullYear() === year &&
      today.getMonth() === month &&
      today.getDate() === d;
    const key = toDateKey(year, month, d);
    const holidayList = holidaysYear[key];
    const isHoliday = !!holidayList && holidayList.length > 0;
    const holidayName = isHoliday ? holidayList.map((h) => h.name || h.localName).filter((v, idx, arr) => arr.indexOf(v) === idx).join(' / ') : '';
    const dateStr = `${new Intl.DateTimeFormat('en-US', { month: 'short' }).format(new Date(year, month, d))} ${d}`;

    let cls = 'cal-day';
    if (isToday) cls += ' cal-today';
    if (isHoliday) cls += ' cal-holiday';

    html += `<div class="${cls}" data-day="${d}" ${isHoliday ? `data-holiday="${escapeHtml(holidayName)}" data-date-str="${dateStr}" title="${escapeHtml(holidayName)}"` : ''}>${d}</div>`;
  }

  // Next month padding to complete grid
  const cellsRendered = firstDay + totalDays;
  const nextMonthPadding = (7 - (cellsRendered % 7)) % 7;
  for (let d = 1; d <= nextMonthPadding; d++) {
    const key = toDateKey(nextYear, nextMonthIdx, d);
    const holidayList = nextHolidaysYear[key];
    const isHoliday = !!holidayList && holidayList.length > 0;
    const holidayName = isHoliday ? holidayList.map((h) => h.name || h.localName).filter((v, idx, arr) => arr.indexOf(v) === idx).join(' / ') : '';
    const dateStr = `${new Intl.DateTimeFormat('en-US', { month: 'short' }).format(new Date(nextYear, nextMonthIdx, d))} ${d}`;
    html += `<div class="cal-day cal-other-month${isHoliday ? ' cal-holiday' : ''}" data-day="${d}" ${isHoliday ? `data-holiday="${escapeHtml(holidayName)}" data-date-str="${dateStr}" title="${escapeHtml(holidayName)}"` : ''}>${d}</div>`;
  }

  grid.innerHTML = html;

  renderGlanceBarForCurrentView();
}

/* =========================================================================
   Weather Widget Logic
   ========================================================================= */
export function getWeatherInfo(code) {
  if (code === 0) return { icon: '☀️', desc: 'Clear Sky' };
  if (code === 1) return { icon: '🌤️', desc: 'Mainly Clear' };
  if (code === 2) return { icon: '⛅', desc: 'Partly Cloudy' };
  if (code === 3) return { icon: '☁️', desc: 'Overcast' };
  if (code === 45 || code === 48) return { icon: '🌫️', desc: 'Foggy' };
  if (code >= 51 && code <= 55) return { icon: '🌦️', desc: 'Drizzle' };
  if (code >= 61 && code <= 65) return { icon: '🌧️', desc: 'Rain' };
  if (code >= 71 && code <= 77) return { icon: '🌨️', desc: 'Snow' };
  if (code >= 80 && code <= 82) return { icon: '🌧️', desc: 'Showers' };
  if (code >= 85 && code <= 86) return { icon: '🌨️', desc: 'Snow Showers' };
  if (code >= 95) return { icon: '⛈️', desc: 'Thunderstorm' };
  return { icon: '⛅', desc: 'Partly Cloudy' };
}

function renderWeatherUI(weatherData) {
  if (!weatherData) return;
  const weatherWidget = document.getElementById('widget-weather');
  if (!weatherWidget) return;

  const cityBadge = document.getElementById('w-weather-city');
  const iconEl = document.getElementById('w-weather-icon');
  const tempEl = document.getElementById('w-weather-temp');
  const descEl = document.getElementById('w-weather-desc');
  const rangeEl = document.getElementById('w-weather-range');
  const detailsEl = document.getElementById('w-weather-details');

  const unit = _config?.weatherUnit || 'c';
  const toUnit = (c) => (unit === 'f' ? Math.round((c * 9) / 5 + 32) : Math.round(c));
  const unitSym = unit === 'f' ? '°F' : '°C';

  const info = getWeatherInfo(weatherData.code);

  if (cityBadge) {
    cityBadge.textContent = weatherData.city || 'Local';
    cityBadge.title = weatherData.city || 'Detected Location';
  }
  if (iconEl) iconEl.textContent = info.icon;
  if (descEl) descEl.textContent = info.desc;
  if (tempEl) tempEl.textContent = `${toUnit(weatherData.tempC)}${unitSym}`;
  if (rangeEl) rangeEl.textContent = `H: ${toUnit(weatherData.highC)}° L: ${toUnit(weatherData.lowC)}°`;
  if (detailsEl) detailsEl.textContent = `💧 ${weatherData.humidity}% • 💨 ${Math.round(weatherData.wind)} km/h`;
}

export async function fetchWeather(force = false) {
  const config = _config || loadWidgetConfig();
  if (!config.enabled || !config.widgets.weather) return;

  let lat = config.weatherLat ?? null;
  let lon = config.weatherLon ?? null;
  let cityName = config.weatherCity?.trim() || '';

  // City-specific cache key to prevent stale cross-city data
  const cacheKey = `${WEATHER_CACHE_KEY}_${cityName || 'auto'}_${config.weatherUnit || 'c'}`;

  // Check cache first
  try {
    const cached = localStorage.getItem(cacheKey);
    if (cached) {
      const parsed = JSON.parse(cached);
      // Valid for 20 minutes (1200000 ms) unless force requested
      if (!force && Date.now() - parsed.timestamp < 1200000) {
        renderWeatherUI(parsed.data);
        return;
      }
      renderWeatherUI(parsed.data);
    }
  } catch (e) {}

  try {
    // 1. If city name is specified but no lat/lon, geocode it
    if (cityName && (lat == null || lon == null)) {
      const geoUrl = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(cityName)}&count=1&language=en&format=json`;
      const geoRes = await fetch(geoUrl);
      const geoData = await geoRes.json();
      if (geoData.results && geoData.results.length) {
        lat = geoData.results[0].latitude;
        lon = geoData.results[0].longitude;
        cityName = geoData.results[0].name;
        // Save lat/lon to avoid repeat geocoding
        saveWidgetConfig({ weatherLat: lat, weatherLon: lon, weatherCity: cityName });
      }
    }

    // 2. If no city name, resolve browser timezone
    if (lat == null || lon == null) {
      let tzCity = '';
      try {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
        if (tz && tz.includes('/')) {
          tzCity = tz.split('/')[1].replace(/_/g, ' ');
        }
      } catch (e) {}

      if (tzCity) {
        const geoUrl = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(tzCity)}&count=1&language=en&format=json`;
        const geoRes = await fetch(geoUrl);
        const geoData = await geoRes.json();
        if (geoData.results && geoData.results.length) {
          lat = geoData.results[0].latitude;
          lon = geoData.results[0].longitude;
          cityName = geoData.results[0].name;
        }
      }
    }

    // 3. Fallback to default coordinates if unresolved
    if (lat == null || lon == null) {
      lat = 40.71;
      lon = -74.01;
      cityName = cityName || 'Local';
    }

    const weatherUrl = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min&timezone=auto`;
    const res = await fetch(weatherUrl);
    if (!res.ok) throw new Error(`Weather fetch failed: ${res.status}`);
    const data = await res.json();

    const weatherData = {
      city: cityName,
      tempC: data.current.temperature_2m,
      humidity: data.current.relative_humidity_2m,
      code: data.current.weather_code,
      wind: data.current.wind_speed_10m,
      highC: data.daily?.temperature_2m_max?.[0] ?? data.current.temperature_2m,
      lowC: data.daily?.temperature_2m_min?.[0] ?? data.current.temperature_2m,
    };

    localStorage.setItem(
      cacheKey,
      JSON.stringify({
        timestamp: Date.now(),
        data: weatherData,
      })
    );

    renderWeatherUI(weatherData);
  } catch (err) {
    console.warn('Weather update error:', err);
    const descEl = document.getElementById('w-weather-desc');
    if (descEl) {
      descEl.textContent = 'Offline';
    }
  }
}

/* =========================================================================
   Weather City Autocomplete Dropdown
   ========================================================================= */
function initWeatherCityAutocomplete() {
  const cityInput = document.getElementById('widget-weather-city-input');
  const dropdown = document.getElementById('widget-weather-city-dropdown');
  const spinner = document.getElementById('widget-weather-city-spinner');
  if (!cityInput || !dropdown) return;

  function closeDropdown() {
    dropdown.style.display = 'none';
    dropdown.innerHTML = '';
    _currentSuggestions = [];
    _activeSuggestionIndex = -1;
    if (spinner) spinner.style.display = 'none';
  }

  function selectCity(item) {
    cityInput.value = item.name;
    closeDropdown();
    saveWidgetConfig({
      weatherCity: item.name,
      weatherLat: item.latitude,
      weatherLon: item.longitude,
      weatherCountry: item.country_code || item.country || '',
    });
    fetchWeather(true);
    const locationDesc = [item.name, item.admin1, item.country_code || item.country].filter(Boolean).join(', ');
    showToast(`Weather location set to ${locationDesc}`, 'success');
  }

  function renderDropdown(items) {
    _currentSuggestions = items;
    _activeSuggestionIndex = -1;
    if (!items.length) {
      dropdown.innerHTML = `<div style="padding: 10px 12px; font-size: 11.5px; color: var(--muted); text-align: center;">No matching cities found</div>`;
      dropdown.style.display = 'block';
      return;
    }

    let html = '';
    items.forEach((item, idx) => {
      const region = [item.admin1, item.country].filter(Boolean).join(', ');
      const code = item.country_code || '';
      html += `
        <div class="weather-city-item" data-idx="${idx}">
          <div>
            <div class="weather-city-name">${item.name}</div>
            <div class="weather-city-sub">${region}</div>
          </div>
          ${code ? `<span class="weather-city-badge">${code}</span>` : ''}
        </div>
      `;
    });
    dropdown.innerHTML = html;
    dropdown.style.display = 'block';

    dropdown.querySelectorAll('.weather-city-item').forEach((el) => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt(el.dataset.idx, 10);
        if (_currentSuggestions[idx]) {
          selectCity(_currentSuggestions[idx]);
        }
      });
      el.addEventListener('mouseenter', () => {
        const idx = parseInt(el.dataset.idx, 10);
        highlightSuggestion(idx);
      });
    });
  }

  function highlightSuggestion(index) {
    _activeSuggestionIndex = index;
    const items = dropdown.querySelectorAll('.weather-city-item');
    items.forEach((item, i) => {
      if (i === index) {
        item.classList.add('active');
        item.scrollIntoView({ block: 'nearest' });
      } else {
        item.classList.remove('active');
      }
    });
  }

  cityInput.addEventListener('input', (e) => {
    const q = e.target.value.trim();
    if (_geoDebounceTimer) clearTimeout(_geoDebounceTimer);

    if (!q) {
      // Suggest returning to Auto-detect
      dropdown.innerHTML = `
        <div class="weather-city-item auto-detect-item" style="cursor: pointer;">
          <div>
            <div class="weather-city-name">📍 Auto-detect Location</div>
            <div class="weather-city-sub">Use local IP & Timezone</div>
          </div>
        </div>
      `;
      dropdown.style.display = 'block';
      dropdown.querySelector('.auto-detect-item')?.addEventListener('click', (ev) => {
        ev.stopPropagation();
        cityInput.value = '';
        closeDropdown();
        saveWidgetConfig({ weatherCity: '', weatherLat: null, weatherLon: null, weatherCountry: '' });
        fetchWeather(true);
        showToast('Weather location reset to Auto-detect', 'success');
      });
      if (spinner) spinner.style.display = 'none';
      return;
    }

    if (q.length < 2) {
      closeDropdown();
      return;
    }

    if (spinner) spinner.style.display = 'inline-block';

    _geoDebounceTimer = setTimeout(async () => {
      try {
        const res = await fetch(
          `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=6&language=en&format=json`
        );
        const data = await res.json();
        if (spinner) spinner.style.display = 'none';
        renderDropdown(data.results || []);
      } catch (err) {
        if (spinner) spinner.style.display = 'none';
        console.warn('Geocoding error:', err);
      }
    }, 250);
  });

  cityInput.addEventListener('keydown', (e) => {
    if (dropdown.style.display === 'none') {
      if (e.key === 'Enter') {
        e.preventDefault();
        const q = cityInput.value.trim();
        saveWidgetConfig({ weatherCity: q, weatherLat: null, weatherLon: null });
        fetchWeather(true);
        if (q) showToast(`Weather location set to ${q}`, 'success');
        else showToast('Weather location set to Auto-detect', 'success');
      }
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const nextIdx = Math.min(_activeSuggestionIndex + 1, _currentSuggestions.length - 1);
      highlightSuggestion(nextIdx);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prevIdx = Math.max(_activeSuggestionIndex - 1, 0);
      highlightSuggestion(prevIdx);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (_activeSuggestionIndex >= 0 && _currentSuggestions[_activeSuggestionIndex]) {
        selectCity(_currentSuggestions[_activeSuggestionIndex]);
      } else if (_currentSuggestions.length > 0) {
        selectCity(_currentSuggestions[0]);
      } else {
        const q = cityInput.value.trim();
        closeDropdown();
        saveWidgetConfig({ weatherCity: q, weatherLat: null, weatherLon: null });
        fetchWeather(true);
      }
    } else if (e.key === 'Escape') {
      closeDropdown();
    }
  });

  // Close when clicking outside
  document.addEventListener('click', (e) => {
    if (!cityInput.contains(e.target) && !dropdown.contains(e.target)) {
      closeDropdown();
    }
  });
}

export function setupWidgetSettingsEvents() {
  const toggleMaster = document.getElementById('widget-toggle-master');
  const posSelect = document.getElementById('widget-pos-select');
  const opacitySelect = document.getElementById('widget-opacity-select');
  const scaleSelect = document.getElementById('widget-scale-select');

  const chkClock = document.getElementById('w-cfg-clock');
  const chkCalendar = document.getElementById('w-cfg-calendar');
  const chkWeather = document.getElementById('w-cfg-weather');
  const chkSystem = document.getElementById('w-cfg-system');
  const chkNetwork = document.getElementById('w-cfg-network');
  const chkStorage = document.getElementById('w-cfg-storage');
  const chkUptime = document.getElementById('w-cfg-uptime');

  const weatherUnitSelect = document.getElementById('widget-weather-unit-select');
  const resetBtn = document.getElementById('widget-reset-defaults-btn');

  if (toggleMaster) {
    toggleMaster.addEventListener('change', (e) => {
      saveWidgetConfig({ enabled: e.target.checked });
    });
  }

  if (posSelect) {
    posSelect.addEventListener('change', (e) => {
      saveWidgetConfig({ position: e.target.value });
    });
  }

  if (opacitySelect) {
    opacitySelect.addEventListener('change', (e) => {
      saveWidgetConfig({ opacity: e.target.value });
    });
  }

  if (scaleSelect) {
    scaleSelect.addEventListener('change', (e) => {
      saveWidgetConfig({ scale: e.target.value });
    });
  }

  const updateSubWidgets = () => {
    const widgets = {
      clock: chkClock ? chkClock.checked : true,
      calendar: chkCalendar ? chkCalendar.checked : false,
      weather: chkWeather ? chkWeather.checked : true,
      system: chkSystem ? chkSystem.checked : true,
      network: chkNetwork ? chkNetwork.checked : true,
      storage: chkStorage ? chkStorage.checked : true,
      uptime: chkUptime ? chkUptime.checked : false,
    };
    saveWidgetConfig({ widgets });
  };

  if (chkClock) chkClock.addEventListener('change', updateSubWidgets);
  if (chkCalendar) chkCalendar.addEventListener('change', updateSubWidgets);
  if (chkWeather) chkWeather.addEventListener('change', updateSubWidgets);
  if (chkSystem) chkSystem.addEventListener('change', updateSubWidgets);
  if (chkNetwork) chkNetwork.addEventListener('change', updateSubWidgets);
  if (chkStorage) chkStorage.addEventListener('change', updateSubWidgets);
  if (chkUptime) chkUptime.addEventListener('change', updateSubWidgets);

  if (weatherUnitSelect) {
    weatherUnitSelect.addEventListener('change', (e) => {
      saveWidgetConfig({ weatherUnit: e.target.value });
      try {
        const config = _config || loadWidgetConfig();
        const cityName = config.weatherCity?.trim() || '';
        const cacheKey = `${WEATHER_CACHE_KEY}_${cityName || 'auto'}_${config.weatherUnit || 'c'}`;
        const cached = localStorage.getItem(cacheKey);
        if (cached) renderWeatherUI(JSON.parse(cached).data);
        else fetchWeather(true);
      } catch (err) {}
    });
  }

  // Initialize City Autocomplete Dropdown
  initWeatherCityAutocomplete();

  // Interactive header controls
  const tzBadge = document.getElementById('w-clock-tz');
  if (tzBadge) {
    tzBadge.addEventListener('click', () => {
      const curFmt = _config?.clockFormat || state.clockFormat || '24';
      const nextFmt = curFmt === '24' ? '12' : '24';
      state.clockFormat = nextFmt;
      saveWidgetConfig({ clockFormat: nextFmt });
      updateClock();
    });
  }

  const calPrev = document.getElementById('w-cal-prev');
  const calNext = document.getElementById('w-cal-next');
  const calMonth = document.getElementById('w-cal-month');

  if (calPrev) {
    calPrev.addEventListener('click', (e) => {
      e.stopPropagation();
      _calViewDate.setMonth(_calViewDate.getMonth() - 1);
      renderCalendar();
    });
  }
  if (calNext) {
    calNext.addEventListener('click', (e) => {
      e.stopPropagation();
      _calViewDate.setMonth(_calViewDate.getMonth() + 1);
      renderCalendar();
    });
  }
  if (calMonth) {
    calMonth.addEventListener('click', (e) => {
      e.stopPropagation();
      _calViewDate = new Date();
      renderCalendar();
    });
  }

  const calCountrySelect = document.getElementById('widget-calendar-country-select');
  if (calCountrySelect) {
    calCountrySelect.addEventListener('change', (e) => {
      saveWidgetConfig({ calendarCountry: e.target.value });
      renderCalendar();
      const cName = e.target.value === 'auto' ? 'Auto-detect' : (COUNTRY_NAMES[e.target.value] || e.target.value);
      showToast(`Calendar holidays set to ${cName}`, 'success');
    });
  }

  const calHolidayToggle = document.getElementById('w-cfg-holiday-toggle');
  if (calHolidayToggle) {
    calHolidayToggle.addEventListener('change', (e) => {
      saveWidgetConfig({ calendarHolidays: e.target.checked });
      renderCalendar();
      showToast(`Calendar holidays ${e.target.checked ? 'enabled' : 'disabled'}`, 'info');
    });
  }

  const calCountryBadge = document.getElementById('w-cal-country-badge');
  if (calCountryBadge) {
    calCountryBadge.addEventListener('click', (e) => {
      e.stopPropagation();
      const mgmtBtn = document.querySelector('[data-mgmt-target="mgmt-sec-wallpaper"]');
      if (mgmtBtn) mgmtBtn.click();
      const widgetSubTab = document.querySelector('[data-subtab="mgmt-pane-widgets"]');
      if (widgetSubTab) widgetSubTab.click();
      const mgmtModal = document.getElementById('management-modal-overlay');
      if (mgmtModal && (mgmtModal.style.display === 'none' || !mgmtModal.classList.contains('visible'))) {
        const openMgmt = document.getElementById('dock-item-management');
        if (openMgmt) openMgmt.click();
      }
    });
  }

  const calGrid = document.getElementById('w-calendar-grid');
  if (calGrid) {
    calGrid.addEventListener('mouseover', (e) => {
      const cell = e.target.closest('.cal-day.cal-holiday');
      if (!cell) return;
      const holidayName = cell.getAttribute('data-holiday');
      const holidayDate = cell.getAttribute('data-date-str');
      if (holidayName) {
        showCalendarTooltip(cell, holidayName, holidayDate);
      }
    });

    calGrid.addEventListener('mouseout', (e) => {
      const cell = e.target.closest('.cal-day.cal-holiday');
      if (cell) {
        hideCalendarTooltip();
      }
    });
  }

  const weatherTemp = document.getElementById('w-weather-temp');
  if (weatherTemp) {
    weatherTemp.addEventListener('click', () => {
      const curUnit = _config?.weatherUnit || 'c';
      const nextUnit = curUnit === 'c' ? 'f' : 'c';
      saveWidgetConfig({ weatherUnit: nextUnit });
      try {
        const config = _config || loadWidgetConfig();
        const cityName = config.weatherCity?.trim() || '';
        const cacheKey = `${WEATHER_CACHE_KEY}_${cityName || 'auto'}_${nextUnit}`;
        const cached = localStorage.getItem(cacheKey);
        if (cached) renderWeatherUI(JSON.parse(cached).data);
        else fetchWeather(true);
      } catch (err) {}
    });
  }

  // Setup drag and drop for Available Widgets list
  const sortableList = document.getElementById('widget-sortable-list');
  if (sortableList) {
    let draggedItem = null;

    const items = sortableList.querySelectorAll('.widget-sortable-item');
    items.forEach((item) => {
      const chk = item.querySelector('input[type="checkbox"]');
      if (chk) {
        chk.addEventListener('mousedown', (e) => e.stopPropagation());
      }

      item.addEventListener('dragstart', (e) => {
        draggedItem = item;
        item.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', item.dataset.widgetId);
      });

      item.addEventListener('dragend', () => {
        if (draggedItem) {
          draggedItem.classList.remove('dragging');
          draggedItem = null;
        }
        sortableList.querySelectorAll('.widget-sortable-item').forEach((i) => {
          i.classList.remove('drag-over-top', 'drag-over-bottom');
        });
      });

      item.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        if (!draggedItem || draggedItem === item) return;

        const rect = item.getBoundingClientRect();
        const midY = rect.top + rect.height / 2;
        if (e.clientY < midY) {
          item.classList.add('drag-over-top');
          item.classList.remove('drag-over-bottom');
        } else {
          item.classList.add('drag-over-bottom');
          item.classList.remove('drag-over-top');
        }
      });

      item.addEventListener('dragleave', (e) => {
        const rect = item.getBoundingClientRect();
        if (
          e.clientX < rect.left ||
          e.clientX >= rect.right ||
          e.clientY < rect.top ||
          e.clientY >= rect.bottom
        ) {
          item.classList.remove('drag-over-top', 'drag-over-bottom');
        }
      });

      item.addEventListener('drop', (e) => {
        e.preventDefault();
        if (!draggedItem || draggedItem === item) return;

        const isAbove = item.classList.contains('drag-over-top');
        item.classList.remove('drag-over-top', 'drag-over-bottom');

        if (isAbove) {
          sortableList.insertBefore(draggedItem, item);
        } else {
          sortableList.insertBefore(draggedItem, item.nextSibling);
        }

        const newOrder = Array.from(sortableList.querySelectorAll('.widget-sortable-item'))
          .map((el) => el.dataset.widgetId)
          .filter(Boolean);

        saveWidgetConfig({ order: newOrder });
      });
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      _config = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
      try {
        localStorage.removeItem(STORAGE_KEY);
        // Clear any weather cache
        Object.keys(localStorage).forEach((k) => {
          if (k.startsWith(WEATHER_CACHE_KEY)) localStorage.removeItem(k);
        });
      } catch (e) {}
      applyWidgetConfig();
      syncWidgetSettingsUI();
      fetchWeather(true);
      showToast('Widgets reset to defaults', 'info');
    });
  }
}

export function initWidgets() {
  loadWidgetConfig();
  applyWidgetConfig();
  setupWidgetSettingsEvents();
  syncWidgetSettingsUI();

  // Clock tick interval
  if (!_clockInterval) {
    _clockInterval = setInterval(updateClock, 1000);
  }

  // Weather refresh interval (every 20 minutes)
  if (!_weatherInterval) {
    _weatherInterval = setInterval(() => fetchWeather(), 20 * 60 * 1000);
  }

  ZettEventBus.on('stats:updated', (stats) => {
    if (!stats || document.hidden) return;

    // CPU
    if (stats.cpu) {
      const cpuVal = stats.cpu.util ?? stats.cpu.load ?? 0;
      const cpuElem = document.getElementById('w-cpu-val');
      const cpuBar = document.getElementById('w-cpu-bar');
      if (cpuElem) cpuElem.textContent = `${cpuVal}%`;
      if (cpuBar) cpuBar.style.width = `${Math.min(100, Math.max(0, cpuVal))}%`;
    }

    // RAM
    if (stats.mem) {
      const ramPct = stats.mem.pct ?? stats.mem.percent ?? 0;
      const ramElem = document.getElementById('w-ram-val');
      const ramBar = document.getElementById('w-ram-bar');
      if (ramElem) ramElem.textContent = `${ramPct}%`;
      if (ramBar) ramBar.style.width = `${Math.min(100, Math.max(0, ramPct))}%`;
    }

    // Network IO
    if (stats.net) {
      const elRx = document.getElementById('w-net-rx');
      const elTx = document.getElementById('w-net-tx');
      const elIface = document.getElementById('w-net-iface');

      const rxText = stats.net.rx ?? (stats.net.rx_rate !== undefined ? formatSpeed(stats.net.rx_rate) : '0 B/s');
      const txText = stats.net.tx ?? (stats.net.tx_rate !== undefined ? formatSpeed(stats.net.tx_rate) : '0 B/s');

      if (elRx) elRx.textContent = rxText;
      if (elTx) elTx.textContent = txText;
      if (elIface && stats.net.iface) {
        elIface.textContent = stats.net.iface;
      }
    }

    // Storage Pool
    if (stats.storage) {
      const elVal = document.getElementById('w-storage-val');
      const elBar = document.getElementById('w-storage-bar');
      const elStatus = document.getElementById('w-storage-status');
      if (elVal) elVal.textContent = `${stats.storage.used} / ${stats.storage.total}`;
      if (elBar) elBar.style.width = `${Math.min(100, Math.max(0, stats.storage.pct || 0))}%`;
      if (elStatus && stats.unraid) {
        elStatus.textContent = stats.unraid.state || 'ONLINE';
      }
    }

    // Host & Uptime
    if (stats.name || stats.uptime) {
      const elHost = document.getElementById('w-host-name');
      const elUptime = document.getElementById('w-host-uptime');
      if (elHost && stats.name) elHost.textContent = stats.name;
      if (elUptime && stats.uptime) elUptime.textContent = stats.uptime;
    }
  });
}
