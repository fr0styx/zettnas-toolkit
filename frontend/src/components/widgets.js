import { ensureManagementDom, onManagementDom } from '../management-dom.js';
import { ZettEventBus } from '../event-bus.js';
import { state } from '../state.js';
import { showToast } from '../toast.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { api, auth } from '../api.js';
import { makeDraggable } from './dock.js';

import { formatDate, formatNumber } from '../format.js';
const STORAGE_KEY = 'zettnas_widgets_config';
const WEATHER_CACHE_KEY = 'zettnas_weather_cache';

const DEFAULT_CONFIG = {
  enabled: true,
  position: 'pos-top-right',
  opacity: 'glass-standard',
  scale: 'scale-normal',
  order: ['clock', 'ai_accelerator', 'weather', 'calendar', 'system', 'network', 'storage', 'uptime', 'drive_temp', 'net_dial', 'ups_gauge'],
  widgets: {
    clock: true,
    ai_accelerator: true,
    calendar: false,
    weather: true,
    system: true,
    network: true,
    storage: true,
    uptime: false,
    drive_temp: true,
    net_dial: true,
    ups_gauge: true,
  },
  clockFormat: '24',
  clockTimezone: 'auto',
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

// Timezone and Calendar Notes State
let _calendarEventsMap = {};
let _calendarFeeds = [];
let _modalCalDate = new Date();
let _modalCalSelectedDateKey = null;
let _calActiveFilter = 'all';
let _tempSelectedTz = 'auto';
let _tempSelectedFormat = '24';
let _tzPreviewTimer = null;
let _tzActiveRegion = 'all';
let _tzSearchQuery = '';

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
window.saveWidgetConfig = saveWidgetConfig;

export const WIDGET_NAMES = {
  clock: 'Time Clock',
  ai_accelerator: 'AI Accelerator',
  calendar: 'Calendar',
  weather: 'Local Weather',
  system: 'System Status',
  network: 'Network I/O',
  storage: 'Storage Pool',
  uptime: 'Host Uptime',
  drive_temp: 'Disk Temperatures',
  net_dial: 'Network Dial',
  ups_gauge: 'UPS Gauge',
};

export function getWidgetKeyFromElement(el) {
  if (!el) return null;
  const widgetNode = el.closest ? el.closest('.desktop-widget') : null;
  if (!widgetNode || !widgetNode.id) return null;
  const id = widgetNode.id;
  if (!id.startsWith('widget-')) return null;
  const rawKey = id.replace('widget-', '');
  if (rawKey === 'ai-accelerator' || rawKey === 'ai_accelerator') return 'ai_accelerator';
  if (rawKey === 'drive-temp' || rawKey === 'drive_temp') return 'drive_temp';
  if (rawKey === 'net-dial' || rawKey === 'net_dial') return 'net_dial';
  if (rawKey === 'ups-gauge' || rawKey === 'ups_gauge') return 'ups_gauge';
  return rawKey;
}
window.getWidgetKeyFromElement = getWidgetKeyFromElement;

export function getWidgetDisplayName(widgetKey) {
  if (!widgetKey) return 'Widget';
  const i18nKey = `widget.${widgetKey}`;
  const translated = t(i18nKey);
  if (translated && translated !== i18nKey) return translated;
  return WIDGET_NAMES[widgetKey] || 'Widget';
}
window.getWidgetDisplayName = getWidgetDisplayName;

export function removeWidget(widgetKey) {
  if (!widgetKey) return;
  const config = _config || loadWidgetConfig();
  const currentWidgets = Object.assign({}, config.widgets || {});
  currentWidgets[widgetKey] = false;
  saveWidgetConfig({ widgets: currentWidgets });
  const name = getWidgetDisplayName(widgetKey);
  const toastMsg = (t('widget.removed_toast') || '{name} removed from desktop').replace('{name}', name);
  showToast(toastMsg, 'info');
}
window.removeWidget = removeWidget;

export function openWidgetSettings() {
  saveWidgetConfig({ enabled: true });
  if (typeof window.openPersonalizationWindow === 'function') {
    window.openPersonalizationWindow('widgets');
  } else if (typeof window.openManagementSection === 'function') {
    window.openManagementSection('mgmt-sec-wallpaper', 'mgmt-pane-widgets');
  } else {
    ZettEventBus.emit('window:open', { id: 'management-window', section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-widgets' });
  }
}
window.openWidgetSettings = openWidgetSettings;

export function applyWidgetConfig() {
  const container = document.getElementById('desktop-widgets-container');
  if (!container) return;

  const config = _config || loadWidgetConfig();

  // Master visibility
  container.style.display = config.enabled ? 'flex' : 'none';

  // Position
  const targetPos = config.position || 'pos-top-right';
  ['pos-top-right', 'pos-top-left', 'pos-bottom-right', 'pos-bottom-left'].forEach((cls) => {
    if (cls !== targetPos) container.classList.remove(cls);
  });
  container.classList.add(targetPos);

  // Opacity / Glass
  const targetOpacity = config.opacity || 'glass-standard';
  ['glass-subtle', 'glass-standard', 'glass-solid'].forEach((cls) => {
    if (cls !== targetOpacity) container.classList.remove(cls);
  });
  container.classList.add(targetOpacity);

  // Scale
  const targetScale = config.scale || 'scale-normal';
  ['scale-compact', 'scale-normal', 'scale-large'].forEach((cls) => {
    if (cls !== targetScale) container.classList.remove(cls);
  });
  container.classList.add(targetScale);

  // Sub-widgets visibility
  const wClock = document.getElementById('widget-clock');
  const wAiAccel = document.getElementById('widget-ai-accelerator') || document.getElementById('widget-ai_accelerator');
  const wCalendar = document.getElementById('widget-calendar');
  const wWeather = document.getElementById('widget-weather');
  const wSystem = document.getElementById('widget-system');
  const wNetwork = document.getElementById('widget-network');
  const wStorage = document.getElementById('widget-storage');
  const wUptime = document.getElementById('widget-uptime');
  const wDriveTemp = document.getElementById('widget-drive-temp');
  const wNetDial = document.getElementById('widget-net-dial');
  const wUpsGauge = document.getElementById('widget-ups-gauge');

  if (wClock) {
    wClock.style.display = config.widgets.clock ? 'block' : 'none';
    if (!wClock.dataset.boundClick) {
      wClock.dataset.boundClick = '1';
      wClock.style.cursor = 'pointer';
      wClock.title = t('ui.click_to_change_timezone_clock', 'Click to change timezone & clock format');
      wClock.setAttribute('role', 'button');
      wClock.setAttribute('tabindex', '0');
      wClock.addEventListener('click', (e) => {
        if (e.target.closest('.widget-handle') || e.target.closest('.widget-close') || e.target.closest('#w-clock-tz')) return;
        openTimezoneModal();
      });
      wClock.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.target === wClock) {
            e.preventDefault();
            openTimezoneModal();
          }
        }
      });
    }
  }
  if (wAiAccel) {
    wAiAccel.style.display = config.widgets.ai_accelerator !== false ? 'block' : 'none';
    if (!wAiAccel.dataset.boundClick) {
      wAiAccel.dataset.boundClick = '1';
      wAiAccel.style.cursor = 'pointer';
      wAiAccel.title = t('ui.click_to_open_ai_knowledge', 'Click to open AI Knowledge & Search');
      wAiAccel.setAttribute('role', 'button');
      wAiAccel.setAttribute('tabindex', '0');
      wAiAccel.addEventListener('click', (e) => {
        if (e.target.closest('.widget-handle') || e.target.closest('.widget-close') || e.target.closest('button')) return;
        if (typeof window.openManagementWindow === 'function') {
          window.openManagementWindow('mgmt-sec-ai', 'mgmt-pane-ai-rag');
        }
      });
      wAiAccel.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.target === wAiAccel) {
            e.preventDefault();
            if (typeof window.openManagementWindow === 'function') {
              window.openManagementWindow('mgmt-sec-ai', 'mgmt-pane-ai-rag');
            }
          }
        }
      });
    }
  }
  if (wCalendar) {
    wCalendar.style.display = config.widgets.calendar ? 'block' : 'none';
    if (!wCalendar.dataset.boundClick) {
      wCalendar.dataset.boundClick = '1';
      wCalendar.style.cursor = 'pointer';
      wCalendar.title = t('ui.click_to_view_notes_reminders', 'Click to view notes, reminders & calendar sync');
      wCalendar.setAttribute('role', 'button');
      wCalendar.setAttribute('tabindex', '0');
      wCalendar.addEventListener('click', (e) => {
        if (e.target.closest('.widget-handle') || e.target.closest('.widget-close')) return;
        if (e.target.closest('#w-cal-prev') || e.target.closest('#w-cal-next') || e.target.closest('#w-cal-country-badge') || e.target.closest('#w-cal-month')) return;
        const dayCell = e.target.closest('.cal-day');
        let selectedDateKey = null;
        if (dayCell && dayCell.dataset.day) {
          const day = parseInt(dayCell.dataset.day, 10);
          if (dayCell.classList.contains('cal-other-month')) {
            const year = _calViewDate.getFullYear();
            const month = _calViewDate.getMonth();
            const isPrev = day > 15;
            const targetDate = isPrev ? new Date(year, month - 1, day) : new Date(year, month + 1, day);
            selectedDateKey = toDateKey(targetDate.getFullYear(), targetDate.getMonth(), targetDate.getDate());
          } else {
            selectedDateKey = toDateKey(_calViewDate.getFullYear(), _calViewDate.getMonth(), day);
          }
        } else if (e.target.closest('#w-cal-glance-bar')) {
          const glance = e.target.closest('#w-cal-glance-bar');
          if (glance?.dataset?.dateKey) {
            selectedDateKey = glance.dataset.dateKey;
          }
        }
        openCalendarModal(selectedDateKey);
      });
      wCalendar.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.target === wCalendar) {
            e.preventDefault();
            openCalendarModal();
          }
        }
      });
    }
  }
  if (wWeather) {
    wWeather.style.display = config.widgets.weather ? 'block' : 'none';
    if (!wWeather.dataset.boundClick) {
      wWeather.dataset.boundClick = '1';
      wWeather.style.cursor = 'pointer';
      wWeather.title = t('ui.click_to_open_weather_widget', 'Click to open Weather & Widget Settings');
      wWeather.setAttribute('role', 'button');
      wWeather.setAttribute('tabindex', '0');
      wWeather.addEventListener('click', (e) => {
        if (e.target.closest('#w-weather-temp') || e.target.closest('.widget-handle') || e.target.closest('.widget-close') || e.target.closest('button')) return;
        if (typeof window.openManagementWindow === 'function') {
          window.openManagementWindow('mgmt-sec-wallpaper', 'mgmt-pane-widgets');
          setTimeout(() => {
            const cityInput = document.getElementById('widget-weather-city-input');
            if (cityInput) {
              cityInput.focus();
              cityInput.classList.add('element-focus-pulse');
              setTimeout(() => cityInput.classList.remove('element-focus-pulse'), 1500);
            }
          }, 150);
        }
      });
      wWeather.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.target === wWeather) {
            e.preventDefault();
            if (typeof window.openManagementWindow === 'function') {
              window.openManagementWindow('mgmt-sec-wallpaper', 'mgmt-pane-widgets');
            }
          }
        }
      });
    }
  }
  if (wSystem) {
    wSystem.style.display = config.widgets.system ? 'block' : 'none';
    if (!wSystem.dataset.boundClick) {
      wSystem.dataset.boundClick = '1';
      wSystem.style.cursor = 'pointer';
      wSystem.title = t('ui.click_to_open_dashboard_telemetry', 'Click to open Dashboard & Telemetry');
      wSystem.setAttribute('role', 'button');
      wSystem.setAttribute('tabindex', '0');
      wSystem.addEventListener('click', (e) => {
        if (e.target.closest('.widget-handle') || e.target.closest('.widget-close') || e.target.closest('button')) return;
        if (typeof window.openManagementWindow === 'function') {
          window.openManagementWindow('mgmt-sec-activity', 'mgmt-pane-metrics');
        }
      });
      wSystem.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.target === wSystem) {
            e.preventDefault();
            if (typeof window.openManagementWindow === 'function') {
              window.openManagementWindow('mgmt-sec-activity', 'mgmt-pane-metrics');
            }
          }
        }
      });
    }
  }
  if (wNetwork) {
    wNetwork.style.display = config.widgets.network ? 'block' : 'none';
    if (!wNetwork.dataset.boundClick) {
      wNetwork.dataset.boundClick = '1';
      wNetwork.style.cursor = 'pointer';
      wNetwork.title = t('ui.click_to_open_network_switch', 'Click to open Network & Switch Inspector');
      wNetwork.setAttribute('role', 'button');
      wNetwork.setAttribute('tabindex', '0');
      wNetwork.addEventListener('click', (e) => {
        if (e.target.closest('.widget-handle') || e.target.closest('.widget-close') || e.target.closest('button')) return;
        if (typeof window.openManagementWindow === 'function') {
          window.openManagementWindow('mgmt-sec-network', 'mgmt-pane-network');
        }
      });
      wNetwork.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.target === wNetwork) {
            e.preventDefault();
            if (typeof window.openManagementWindow === 'function') {
              window.openManagementWindow('mgmt-sec-network', 'mgmt-pane-network');
            }
          }
        }
      });
    }
  }
  if (wStorage) {
    wStorage.style.display = config.widgets.storage ? 'block' : 'none';
    if (!wStorage.dataset.boundClick) {
      wStorage.dataset.boundClick = '1';
      wStorage.style.cursor = 'pointer';
      wStorage.title = t('ui.click_to_open_storage_pool', 'Click to open Storage Pool & Array Topology');
      wStorage.setAttribute('role', 'button');
      wStorage.setAttribute('tabindex', '0');
      wStorage.addEventListener('click', (e) => {
        if (e.target.closest('.widget-handle') || e.target.closest('.widget-close') || e.target.closest('button')) return;
        if (typeof window.openManagementWindow === 'function') {
          window.openManagementWindow('mgmt-sec-storage', 'mgmt-pane-storage-topo');
        }
      });
      wStorage.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.target === wStorage) {
            e.preventDefault();
            if (typeof window.openManagementWindow === 'function') {
              window.openManagementWindow('mgmt-sec-storage', 'mgmt-pane-storage-topo');
            }
          }
        }
      });
    }
  }
  if (wUptime) {
    wUptime.style.display = config.widgets.uptime ? 'block' : 'none';
    if (!wUptime.dataset.boundClick) {
      wUptime.dataset.boundClick = '1';
      wUptime.style.cursor = 'pointer';
      wUptime.title = t('ui.click_to_open_dashboard_telemetry', 'Click to open Dashboard & Telemetry');
      wUptime.setAttribute('role', 'button');
      wUptime.setAttribute('tabindex', '0');
      wUptime.addEventListener('click', (e) => {
        if (e.target.closest('.widget-handle') || e.target.closest('.widget-close') || e.target.closest('button')) return;
        if (typeof window.openManagementWindow === 'function') {
          window.openManagementWindow('mgmt-sec-activity', 'mgmt-pane-metrics');
        }
      });
      wUptime.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.target === wUptime) {
            e.preventDefault();
            if (typeof window.openManagementWindow === 'function') {
              window.openManagementWindow('mgmt-sec-activity', 'mgmt-pane-metrics');
            }
          }
        }
      });
    }
  }
  if (wDriveTemp) {
    wDriveTemp.style.display = config.widgets.drive_temp !== false ? 'block' : 'none';
    if (!wDriveTemp.dataset.boundClick) {
      wDriveTemp.dataset.boundClick = '1';
      wDriveTemp.style.cursor = 'pointer';
      wDriveTemp.title = t('ui.click_to_open_storage_disks', 'Click to open Storage & Disks');
      wDriveTemp.setAttribute('role', 'button');
      wDriveTemp.setAttribute('tabindex', '0');
      wDriveTemp.addEventListener('click', (e) => {
        if (e.target.closest('.widget-handle') || e.target.closest('.widget-close') || e.target.closest('button')) return;
        if (typeof window.openManagementWindow === 'function') {
          window.openManagementWindow('mgmt-sec-storage');
        }
      });
      wDriveTemp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.target === wDriveTemp) {
            e.preventDefault();
            if (typeof window.openManagementWindow === 'function') {
              window.openManagementWindow('mgmt-sec-storage');
            }
          }
        }
      });
    }
  }
  if (wNetDial) {
    wNetDial.style.display = config.widgets.net_dial !== false ? 'block' : 'none';
    if (!wNetDial.dataset.boundClick) {
      wNetDial.dataset.boundClick = '1';
      wNetDial.style.cursor = 'pointer';
      wNetDial.title = t('ui.click_to_open_network_cockpit', 'Click to open Network Cockpit');
      wNetDial.setAttribute('role', 'button');
      wNetDial.setAttribute('tabindex', '0');
      wNetDial.addEventListener('click', (e) => {
        if (e.target.closest('.widget-handle') || e.target.closest('.widget-close') || e.target.closest('button')) return;
        if (typeof window.openManagementWindow === 'function') {
          window.openManagementWindow('mgmt-sec-network');
        }
      });
      wNetDial.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.target === wNetDial) {
            e.preventDefault();
            if (typeof window.openManagementWindow === 'function') {
              window.openManagementWindow('mgmt-sec-network');
            }
          }
        }
      });
    }
  }
  if (wUpsGauge) {
    wUpsGauge.style.display = config.widgets.ups_gauge !== false ? 'block' : 'none';
    if (!wUpsGauge.dataset.boundClick) {
      wUpsGauge.dataset.boundClick = '1';
      wUpsGauge.style.cursor = 'pointer';
      wUpsGauge.title = t('ui.click_to_open_power_battery', 'Click to open Power & Battery Cockpit');
      wUpsGauge.setAttribute('role', 'button');
      wUpsGauge.setAttribute('tabindex', '0');
      wUpsGauge.addEventListener('click', (e) => {
        if (e.target.closest('.widget-handle') || e.target.closest('.widget-close') || e.target.closest('button')) return;
        if (typeof window.openManagementWindow === 'function') {
          window.openManagementWindow('mgmt-sec-ups');
        }
      });
      wUpsGauge.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.target === wUpsGauge) {
            e.preventDefault();
            if (typeof window.openManagementWindow === 'function') {
              window.openManagementWindow('mgmt-sec-ups');
            }
          }
        }
      });
    }
  }

  // Reorganize desktop widgets in the EXACT same order on the desktop ONLY if order differs
  const order = Array.isArray(config.order) && config.order.length ? config.order : DEFAULT_CONFIG.order;
  const currentChildrenIds = Array.from(container.children).map((el) => el.id.replace('widget-', '').replace(/-/g, '_'));
  const needsReorder = order.some((id, idx) => currentChildrenIds[idx] !== id);
  if (needsReorder) {
    order.forEach((id) => {
      const el = document.getElementById(`widget-${id}`) || document.getElementById(`widget-${id.replace(/_/g, '-')}`);
      if (el && container.contains(el)) {
        container.appendChild(el);
      }
    });
  }

  // Safely remove early-injected style now that all classes and styles are applied
  const earlyStyle = document.getElementById('zettnas-widgets-early-style');
  if (earlyStyle && earlyStyle.parentNode) {
    earlyStyle.parentNode.removeChild(earlyStyle);
  }

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
  const chkAiAccel = document.getElementById('w-cfg-ai-accelerator');
  const chkCalendar = document.getElementById('w-cfg-calendar');
  const chkWeather = document.getElementById('w-cfg-weather');
  const chkSystem = document.getElementById('w-cfg-system');
  const chkNetwork = document.getElementById('w-cfg-network');
  const chkStorage = document.getElementById('w-cfg-storage');
  const chkUptime = document.getElementById('w-cfg-uptime');
  const chkDriveTemp = document.getElementById('w-cfg-drive-temp');
  const chkNetDial = document.getElementById('w-cfg-net-dial');
  const chkUpsGauge = document.getElementById('w-cfg-ups-gauge');

  const weatherCityInput = document.getElementById('widget-weather-city-input');
  const weatherUnitSelect = document.getElementById('widget-weather-unit-select');

  if (toggleMaster) toggleMaster.checked = !!config.enabled;
  if (posSelect) posSelect.value = config.position || 'pos-top-right';
  if (opacitySelect) opacitySelect.value = config.opacity || 'glass-standard';
  if (scaleSelect) scaleSelect.value = config.scale || 'scale-normal';

  if (chkClock) chkClock.checked = !!config.widgets.clock;
  if (chkAiAccel) chkAiAccel.checked = config.widgets.ai_accelerator !== false;
  if (chkCalendar) chkCalendar.checked = !!config.widgets.calendar;
  if (chkWeather) chkWeather.checked = !!config.widgets.weather;
  if (chkSystem) chkSystem.checked = !!config.widgets.system;
  if (chkNetwork) chkNetwork.checked = !!config.widgets.network;
  if (chkStorage) chkStorage.checked = !!config.widgets.storage;
  if (chkUptime) chkUptime.checked = !!config.widgets.uptime;
  if (chkDriveTemp) chkDriveTemp.checked = config.widgets.drive_temp !== false;
  if (chkNetDial) chkNetDial.checked = config.widgets.net_dial !== false;
  if (chkUpsGauge) chkUpsGauge.checked = config.widgets.ups_gauge !== false;

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
  const tz = _config?.clockTimezone || 'auto';

  const timeEl = document.getElementById('w-clock-time');
  const secEl = document.getElementById('w-clock-sec');
  const ampmEl = document.getElementById('w-clock-ampm');
  const dateEl = document.getElementById('w-clock-date');
  const tzBadge = document.getElementById('w-clock-tz');

  let hoursStr = '';
  let minutes = '';
  let seconds = '';
  let ampm = '';
  let tzAbbr = '';

  try {
    const opts = {
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
      hour12: format === '12',
    };
    if (tz && tz !== 'auto') {
      opts.timeZone = tz;
    }
    const formatter = new Intl.DateTimeFormat('en-US', opts);
    const parts = formatter.formatToParts(now);
    for (const part of parts) {
      if (part.type === 'hour') hoursStr = part.value.padStart(2, '0');
      else if (part.type === 'minute') minutes = part.value.padStart(2, '0');
      else if (part.type === 'second') seconds = part.value.padStart(2, '0');
      else if (part.type === 'dayPeriod') ampm = part.value.toUpperCase();
    }
    if (format === '12' && hoursStr.startsWith('0')) {
      hoursStr = hoursStr.replace(/^0/, '');
    }

    if (tz && tz !== 'auto') {
      const tzPart = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'short' })
        .formatToParts(now)
        .find((p) => p.type === 'timeZoneName');
      if (tzPart) tzAbbr = tzPart.value;
    }
  } catch (e) {
    let hours = now.getHours();
    minutes = String(now.getMinutes()).padStart(2, '0');
    seconds = String(now.getSeconds()).padStart(2, '0');
    if (format === '12') {
      ampm = hours >= 12 ? 'PM' : 'AM';
      hours = hours % 12 || 12;
    }
    hoursStr = format === '12' ? String(hours) : String(hours).padStart(2, '0');
  }

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
      const dateOpts = {
        weekday: 'long',
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      };
      if (tz && tz !== 'auto') dateOpts.timeZone = tz;
      const dateStr = formatDate(now, dateOpts);
      dateEl.textContent = dateStr;
    } catch (e) {
      dateEl.textContent = now.toDateString();
    }
  }
  if (tzBadge) {
    if (tz && tz !== 'auto') {
      const city = tz.split('/').pop().replace(/_/g, ' ');
      tzBadge.textContent = `${tzAbbr || city} • ${format === '12' ? '12H' : '24H'}`;
      tzBadge.title = `Timezone: ${tz} (${tzAbbr || city}) - Click to change`;
    } else {
      tzBadge.textContent = format === '12' ? '12H' : '24H';
      tzBadge.title = t('ui.local_timezone_click_to_change', 'Local Timezone - Click to change');
    }
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
      const dateStr = `${formatDate(new Date(year, month, d))} ${d}`;
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
  if (target && target.day) {
    glanceBar.dataset.dateKey = toDateKey(year, month, target.day);
  } else {
    delete glanceBar.dataset.dateKey;
  }
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
    const dateStr = `${formatDate(new Date(prevYear, prevMonthIdx, d))} ${d}`;
    let cls = 'cal-day cal-other-month';
    if (isHoliday) cls += ' cal-holiday';
    const dayEvents = _calendarEventsMap[key];
    if (dayEvents && dayEvents.length > 0) {
      cls += ' has-notes';
      if (dayEvents.some((e) => e.type === 'task')) cls += ' has-task';
    }
    html += `<div class="${cls}" data-day="${d}" ${isHoliday ? `data-holiday="${escapeHtml(holidayName)}" data-date-str="${dateStr}" title="${escapeHtml(holidayName)}"` : ''}>${d}</div>`;
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
    const dateStr = `${formatDate(new Date(year, month, d))} ${d}`;

    let cls = 'cal-day';
    if (isToday) cls += ' cal-today';
    if (isHoliday) cls += ' cal-holiday';
    const dayEvents = _calendarEventsMap[key];
    if (dayEvents && dayEvents.length > 0) {
      cls += ' has-notes';
      if (dayEvents.some((e) => e.type === 'task')) cls += ' has-task';
    }

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
    const dateStr = `${formatDate(new Date(nextYear, nextMonthIdx, d))} ${d}`;
    let cls = 'cal-day cal-other-month';
    if (isHoliday) cls += ' cal-holiday';
    const dayEvents = _calendarEventsMap[key];
    if (dayEvents && dayEvents.length > 0) {
      cls += ' has-notes';
      if (dayEvents.some((e) => e.type === 'task')) cls += ' has-task';
    }
    html += `<div class="${cls}" data-day="${d}" ${isHoliday ? `data-holiday="${escapeHtml(holidayName)}" data-date-str="${dateStr}" title="${escapeHtml(holidayName)}"` : ''}>${d}</div>`;
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
      descEl.textContent = t('ui.offline', 'Offline');
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
    showToast(t('toast.weather_location_set_to', 'Weather location set to {locationDesc}', { locationDesc: locationDesc }), 'success');
  }

  function renderDropdown(items) {
    _currentSuggestions = items;
    _activeSuggestionIndex = -1;
    if (!items.length) {
      dropdown.innerHTML = `<div style="padding: 10px 12px; font-size: var(--zn-fs-xs); color: var(--muted); text-align: center;">No matching cities found</div>`;
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
            <div class="weather-city-name">${escapeHtml(item.name || '')}</div>
            <div class="weather-city-sub">${escapeHtml(region)}</div>
          </div>
          ${code ? `<span class="weather-city-badge">${escapeHtml(code)}</span>` : ''}
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
        showToast(t('toast.weather_location_reset_to_auto_detect', 'Weather location reset to Auto-detect'), 'success');
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
        if (q) showToast(t('toast.weather_location_set_to_2', 'Weather location set to {q}', { q: q }), 'success');
        else showToast(t('toast.weather_location_set_to_auto_detect', 'Weather location set to Auto-detect'), 'success');
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
  const chkAiAccel = document.getElementById('w-cfg-ai-accelerator');
  const chkCalendar = document.getElementById('w-cfg-calendar');
  const chkWeather = document.getElementById('w-cfg-weather');
  const chkSystem = document.getElementById('w-cfg-system');
  const chkNetwork = document.getElementById('w-cfg-network');
  const chkStorage = document.getElementById('w-cfg-storage');
  const chkUptime = document.getElementById('w-cfg-uptime');
  const chkDriveTemp = document.getElementById('w-cfg-drive-temp');
  const chkNetDial = document.getElementById('w-cfg-net-dial');
  const chkUpsGauge = document.getElementById('w-cfg-ups-gauge');

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
      ai_accelerator: chkAiAccel ? chkAiAccel.checked : true,
      calendar: chkCalendar ? chkCalendar.checked : false,
      weather: chkWeather ? chkWeather.checked : true,
      system: chkSystem ? chkSystem.checked : true,
      network: chkNetwork ? chkNetwork.checked : true,
      storage: chkStorage ? chkStorage.checked : true,
      uptime: chkUptime ? chkUptime.checked : false,
      drive_temp: chkDriveTemp ? chkDriveTemp.checked : true,
      net_dial: chkNetDial ? chkNetDial.checked : true,
      ups_gauge: chkUpsGauge ? chkUpsGauge.checked : true,
    };
    saveWidgetConfig({ widgets });
  };

  if (chkClock) chkClock.addEventListener('change', updateSubWidgets);
  if (chkAiAccel) chkAiAccel.addEventListener('change', updateSubWidgets);
  if (chkCalendar) chkCalendar.addEventListener('change', updateSubWidgets);
  if (chkWeather) chkWeather.addEventListener('change', updateSubWidgets);
  if (chkSystem) chkSystem.addEventListener('change', updateSubWidgets);
  if (chkNetwork) chkNetwork.addEventListener('change', updateSubWidgets);
  if (chkStorage) chkStorage.addEventListener('change', updateSubWidgets);
  if (chkUptime) chkUptime.addEventListener('change', updateSubWidgets);
  if (chkDriveTemp) chkDriveTemp.addEventListener('change', updateSubWidgets);
  if (chkNetDial) chkNetDial.addEventListener('change', updateSubWidgets);
  if (chkUpsGauge) chkUpsGauge.addEventListener('change', updateSubWidgets);

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
    tzBadge.addEventListener('click', (e) => {
      e.stopPropagation();
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
      showToast(t('toast.calendar_holidays_set_to', 'Calendar holidays set to {cName}', { cName: cName }), 'success');
    });
  }

  const calHolidayToggle = document.getElementById('w-cfg-holiday-toggle');
  if (calHolidayToggle) {
    calHolidayToggle.addEventListener('change', (e) => {
      saveWidgetConfig({ calendarHolidays: e.target.checked });
      renderCalendar();
      showToast(e.target.checked ? t('toast.calendar_holidays_enabled', 'Calendar holidays enabled') : t('toast.calendar_holidays_disabled', 'Calendar holidays disabled'), 'info');
    });
  }

  const calCountryBadge = document.getElementById('w-cal-country-badge');
  if (calCountryBadge) {
    calCountryBadge.addEventListener('click', (e) => {
      e.stopPropagation();
      if (typeof window.openPersonalizationWindow === 'function') {
        window.openPersonalizationWindow('widgets');
      } else {
        const mgmtBtn = document.querySelector('[data-mgmt-target="mgmt-sec-wallpaper"]');
        if (mgmtBtn) mgmtBtn.click();
        const widgetSubTab = document.querySelector('[data-subtab="mgmt-pane-widgets"]');
        if (widgetSubTab) widgetSubTab.click();
        const mgmtModal = document.getElementById('management-modal-overlay');
        if (mgmtModal && (mgmtModal.style.display === 'none' || !mgmtModal.classList.contains('visible'))) {
          const openMgmt = document.getElementById('dock-item-management');
          if (openMgmt) openMgmt.click();
        }
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
    weatherTemp.addEventListener('click', (e) => {
      e.stopPropagation();
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
      showToast(t('toast.widgets_reset_to_defaults', 'Widgets reset to defaults'), 'info');
    });
  }
}

export function initWidgets() {
  loadWidgetConfig();
  applyWidgetConfig();
  // Widget settings and the clock/calendar pop-ups are in Mission Control (FE-04)
  onManagementDom(() => {
    setupWidgetSettingsEvents();
    syncWidgetSettingsUI();
    setupTimezoneModalEvents();
    setupCalendarModalEvents();
  });

  // Pre-fetch calendar events for desktop widget dots
  try {
    const y = _calViewDate.getFullYear();
    const m = _calViewDate.getMonth();
    fetchCalendarEvents(toDateKey(y, m - 1, 1), toDateKey(y, m + 1, 28));
  } catch (e) {}

  // Clock tick interval
  if (!_clockInterval) {
    _clockInterval = setInterval(updateClock, 1000);
  }

  // Weather refresh interval (every 20 minutes)
  if (!_weatherInterval) {
    _weatherInterval = setInterval(() => fetchWeather(), 20 * 60 * 1000);
  }

  ZettEventBus.on('stats:updated', (stats) => {
    if (!stats) return;
    if (typeof document !== 'undefined' && document.hidden && typeof process === 'undefined') return;
    const container = document.getElementById('desktop-widgets-container');
    if (container && (container.style.display === 'none' || container.classList.contains('hidden') || _config?.enabled === false)) return;

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

    // Drive Thermals Heatmap
    const driveGrid = document.getElementById('w-drive-temp-grid');
    const driveSummary = document.getElementById('w-drive-temp-summary');
    if (driveGrid && stats.disks && Array.isArray(stats.disks)) {
      const disks = stats.disks;
      if (driveSummary) {
        const activeCount = disks.filter((d) => !d.standby && d.temp !== null && d.temp !== undefined).length;
        driveSummary.textContent = `${activeCount}/${disks.length} Active`;
      }
      driveGrid.innerHTML = disks.map((d, idx) => {
        const bayLabel = d.bay !== undefined ? `Bay ${d.bay}` : (d.name || `Disk ${idx + 1}`);
        const isStandby = d.standby || d.temp === null || d.temp === undefined;
        const tempText = isStandby ? 'SLEEP' : `${d.temp}°C`;
        const tempClass = isStandby
          ? 'temp-standby'
          : (d.temp >= 45 ? 'temp-hot' : (d.temp >= 35 ? 'temp-warm' : 'temp-cool'));
        return `
          <div class="drive-temp-cell ${tempClass}" title="${escapeHtml(d.name || '')} - ${tempText}">
            <span class="drive-temp-bay">${escapeHtml(bayLabel)}</span>
            <span class="drive-temp-val">${tempText}</span>
          </div>
        `;
      }).join('');
    }

    // Network Throughput Dial
    const netDialArc = document.getElementById('w-net-dial-arc');
    const netDialPct = document.getElementById('w-net-dial-pct');
    const netDialRx = document.getElementById('w-net-dial-rx');
    const netDialTx = document.getElementById('w-net-dial-tx');
    const netDialSpeed = document.getElementById('w-net-dial-speed');
    if (stats.net) {
      const rxRate = stats.net.rx_rate || 0;
      const txRate = stats.net.tx_rate || 0;
      const linkSpeedMbps = stats.net.speed || 1000;
      if (netDialSpeed) {
        netDialSpeed.textContent = linkSpeedMbps >= 1000 ? `${(linkSpeedMbps / 1000).toFixed(1).replace('.0', '')}G` : `${linkSpeedMbps}M`;
      }
      if (netDialRx) netDialRx.textContent = formatSpeed(rxRate);
      if (netDialTx) netDialTx.textContent = formatSpeed(txRate);

      const maxBytesSec = (linkSpeedMbps * 1000 * 1000) / 8;
      const combinedRate = rxRate + txRate;
      const pct = Math.min(100, Math.round((combinedRate / Math.max(1, maxBytesSec)) * 100));
      if (netDialArc) {
        netDialArc.setAttribute('stroke-dasharray', `${pct}, 100`);
      }
      if (netDialPct) {
        netDialPct.textContent = `${pct}%`;
      }
    }

    // UPS Power Gauge
    const upsBattery = document.getElementById('w-ups-battery');
    const upsBar = document.getElementById('w-ups-bar');
    const upsLoad = document.getElementById('w-ups-load');
    const upsRuntime = document.getElementById('w-ups-runtime');
    const upsBadge = document.getElementById('w-ups-badge');
    if (stats.ups) {
      const charge = stats.ups.battery_charge_pct ?? stats.ups.battery_charge ?? stats.ups.charge ?? 100;
      const loadW = stats.ups.power_watts ?? stats.ups.load_wattage ?? (stats.ups.load_pct != null ? `${stats.ups.load_pct}%` : (stats.ups.load_percent ? `${stats.ups.load_percent}%` : '-- W'));
      const runtimeMin = stats.ups.time_left_min != null ? Math.round(stats.ups.time_left_min) : (stats.ups.runtime_seconds ? Math.round(stats.ups.runtime_seconds / 60) : '--');
      const status = stats.ups.status || 'ONLINE';

      if (upsBattery) upsBattery.textContent = `${charge}%`;
      if (upsBar) {
        upsBar.style.width = `${Math.min(100, Math.max(0, charge))}%`;
        upsBar.style.background = charge < 20 ? 'var(--err, #eb5757)' : (charge < 50 ? 'var(--warn, #f5a623)' : 'var(--ok2, #25c2a0)');
      }
      if (upsLoad) upsLoad.textContent = typeof loadW === 'number' ? `${loadW} W` : String(loadW);
      if (upsRuntime) upsRuntime.textContent = `${runtimeMin} min`;
      if (upsBadge) {
        upsBadge.textContent = status.includes('OB') || status.includes('BATT') ? 'ON BATT' : 'ONLINE';
        upsBadge.style.color = status.includes('OB') ? 'var(--warn, #f5a623)' : 'var(--ok2, #25c2a0)';
      }

      const wUpsGauge = document.getElementById('widget-ups-gauge');
      if (wUpsGauge && !wUpsGauge.dataset.boundClick) {
        wUpsGauge.dataset.boundClick = '1';
        wUpsGauge.style.cursor = 'pointer';
        wUpsGauge.title = t('ui.click_to_open_power_battery', 'Click to open Power & Battery Cockpit');
        wUpsGauge.addEventListener('click', (e) => {
          if (e.target.closest('.widget-handle') || e.target.closest('.widget-close') || e.target.closest('button')) return;
          if (typeof window.openManagementWindow === 'function') {
            window.openManagementWindow('mgmt-sec-ups');
          }
        });
      }
    }

    // AI Accelerator (NPU + GPU Dual Real-Time Gauges)
    const npuArc = document.getElementById('w-ai-npu-arc');
    const npuVal = document.getElementById('w-ai-npu-val');
    const npuFreq = document.getElementById('w-ai-npu-freq');
    const npuState = document.getElementById('w-ai-npu-state');

    const gpuArc = document.getElementById('w-ai-gpu-arc');
    const gpuVal = document.getElementById('w-ai-gpu-val');
    const gpuFreq = document.getElementById('w-ai-gpu-freq');
    const gpuState = document.getElementById('w-ai-gpu-state');

    const aiBadge = document.getElementById('w-ai-accel-badge');
    const aiEngineStatus = document.getElementById('w-ai-engine-status');

    if (stats.npu || stats.gpu) {
      const npu = stats.npu || {};
      const gpu = stats.gpu || {};

      // Measured busy time only; null means the driver can't report it (shown as "–")
      const npuKnown = typeof npu.util_pct === 'number';
      const gpuKnown = typeof gpu.util_pct === 'number';
      const nUtil = npuKnown ? Math.min(100, Math.max(0, Math.round(npu.util_pct))) : 0;
      const gUtil = gpuKnown ? Math.min(100, Math.max(0, Math.round(gpu.util_pct))) : 0;

      if (npuArc) npuArc.setAttribute('stroke-dasharray', `${nUtil}, 100`);
      if (npuVal) npuVal.textContent = npuKnown ? `${nUtil}%` : '–';
      if (npuFreq) {
        const curF = npu.cur_freq_mhz || 0;
        npuFreq.textContent = curF > 0 ? `${curF} MHz` : (npu.present ? '0 MHz' : 'N/A');
      }
      if (npuState) {
        if (!npu.present) {
          npuState.textContent = t('ui.none', 'None');
          npuState.className = 'ai-metric-pill';
        } else if (nUtil > 5 || (npu.cur_freq_mhz && npu.cur_freq_mhz > 400) || npu.power_state === 'D0' || npu.inference_active || (stats.ai_active && stats.ai_accelerator === 'npu')) {
          npuState.textContent = t('ui.active_3w', 'Active');
          npuState.className = 'ai-metric-pill active-npu';
        } else {
          npuState.textContent = t('ui.d3_sleep', 'D3 Sleep');
          npuState.className = 'ai-metric-pill sleep';
        }
      }

      if (gpuArc) gpuArc.setAttribute('stroke-dasharray', `${gUtil}, 100`);
      if (gpuVal) gpuVal.textContent = gpuKnown ? `${gUtil}%` : '–';
      if (gpuFreq) {
        const curG = gpu.cur_freq_mhz || 0;
        gpuFreq.textContent = curG > 0 ? `${curG} MHz` : (gpu.present ? '0 MHz' : 'N/A');
      }
      if (gpuState) {
        if (!gpu.present) {
          gpuState.textContent = t('ui.none', 'None');
          gpuState.className = 'ai-metric-pill';
        } else if (gUtil > 5 || (gpu.cur_freq_mhz && gpu.cur_freq_mhz > 600) || gpu.inference_active || (stats.ai_active && (stats.ai_accelerator === 'gpu' || stats.ai_accelerator === 'arc'))) {
          gpuState.textContent = t('vm.compute', 'Compute');
          gpuState.className = 'ai-metric-pill active-gpu';
        } else {
          gpuState.textContent = t('common.standby', 'Standby');
          gpuState.className = 'ai-metric-pill sleep';
        }
      }

      if (aiBadge) {
        if (nUtil > 0 && gUtil > 0) {
          aiBadge.textContent = 'DUAL RUN';
          aiBadge.style.color = 'var(--brand, #00f0ff)';
        } else if (nUtil > 0 || (stats.ai_active && stats.ai_accelerator === 'npu')) {
          aiBadge.textContent = 'NPU RUN';
          aiBadge.style.color = 'var(--brand, #00f0ff)';
        } else if (gUtil > 0 || (stats.ai_active && (stats.ai_accelerator === 'gpu' || stats.ai_accelerator === 'arc'))) {
          aiBadge.textContent = 'GPU RUN';
          aiBadge.style.color = '#c084fc';
        } else if (npu.present && gpu.present) {
          aiBadge.textContent = 'NPU + GPU';
          aiBadge.style.color = 'var(--ok2, #25c2a0)';
        } else if (npu.present) {
          aiBadge.textContent = 'NPU';
          aiBadge.style.color = 'var(--brand, #00f0ff)';
        } else if (gpu.present) {
          aiBadge.textContent = t('bench.gpu', 'GPU');
          aiBadge.style.color = '#c084fc';
        } else {
          aiBadge.textContent = 'CPU ONLY';
          aiBadge.style.color = 'var(--muted)';
        }
      }

      if (aiEngineStatus) {
        if (nUtil > 0 || (stats.ai_active && stats.ai_accelerator === 'npu')) {
          aiEngineStatus.innerHTML = '<span class="ai-status-dot active"></span> <strong style="color:var(--lt-ink-brand, var(--brand, #00f0ff));">Intel AI Boost NPU Active</strong>';
        } else if (gUtil > 0 || (stats.ai_active && (stats.ai_accelerator === 'gpu' || stats.ai_accelerator === 'arc'))) {
          aiEngineStatus.innerHTML = '<span class="ai-status-dot active-gpu"></span> <strong style="color:var(--zn-text-ai);">Intel Arc GPU Active</strong>';
        } else if (npu.present && gpu.present) {
          aiEngineStatus.innerHTML = '<span class="ai-status-dot standby"></span> <span>Hybrid Dual Silicon</span> <span style="opacity:0.65;">(NPU + GPU Ready)</span>';
        } else {
          aiEngineStatus.innerHTML = '<span class="ai-status-dot standby"></span> <span>Neural Engine Ready</span>';
        }
      }

      // Live Re-indexing Progress Strip in AI Accelerator Desktop Widget
      const wReindexStrip = document.getElementById('w-ai-reindex-strip');
      const wReindexChunks = document.getElementById('w-ai-reindex-chunks');
      const wReindexEta = document.getElementById('w-ai-reindex-eta');
      const wReindexPct = document.getElementById('w-ai-reindex-pct');
      const wReindexBar = document.getElementById('w-ai-reindex-bar');
      const topText = document.getElementById('topbar-ai-accel-text');
      const topDot = document.getElementById('topbar-ai-accel-dot');

      const reindex = stats.reindex_status;
      if (reindex && reindex.status === 'running' && reindex.total > 0 && reindex.completed < reindex.total) {
        const pct = reindex.percentage ?? Math.round((reindex.completed / reindex.total) * 100);
        const etaSec = reindex.eta_sec || 0;
        let etaText = 'ETA: --';
        let etaShort = '';
        if (etaSec > 0) {
          if (etaSec < 60) {
            etaText = `ETA: ${Math.round(etaSec)}s`;
            etaShort = ` • ${Math.round(etaSec)}s`;
          } else if (etaSec < 3600) {
            const mins = Math.floor(etaSec / 60);
            etaText = `ETA: ${mins}m`;
            etaShort = ` • ${mins}m`;
          } else {
            const hrs = Math.floor(etaSec / 3600);
            const mins = Math.round((etaSec % 3600) / 60);
            etaText = `ETA: ${hrs}h ${mins}m`;
            etaShort = ` • ${hrs}h ${mins}m`;
          }
        }

        if (wReindexStrip) {
          wReindexStrip.style.display = 'block';
          if (wReindexBar) wReindexBar.style.width = `${pct}%`;
          if (wReindexPct) wReindexPct.textContent = `${pct}%`;
          if (wReindexChunks) wReindexChunks.textContent = `${formatNumber(reindex.completed || 0)} / ${formatNumber(reindex.total || 0)}`;
          if (wReindexEta) wReindexEta.textContent = etaText;
          if (!wReindexStrip.dataset.bound) {
            wReindexStrip.dataset.bound = '1';
            wReindexStrip.addEventListener('click', (e) => {
              e.stopPropagation();
              if (typeof window.openManagementWindow === 'function') {
                window.openManagementWindow('mgmt-sec-ai', 'mgmt-pane-ai-index');
              }
            });
          }
        }
        if (topText) {
          topText.textContent = `Re-indexing ${pct}%${etaShort}`;
        }
        if (topDot) {
          topDot.style.background = '#00f0ff';
          topDot.style.boxShadow = '0 0 6px #00f0ff';
        }
      } else if (wReindexStrip) {
        wReindexStrip.style.display = 'none';
      }
    }
  });
}

/* =========================================================================
   Timezone & Clock Modal Logic
   ========================================================================= */

export const TIMEZONES_CATALOG = [
  { id: 'UTC', name: 'UTC / GMT', region: 'UTC', country: 'Universal' },
  { id: 'America/New_York', name: 'New York (Eastern)', region: 'Americas', country: 'United States' },
  { id: 'America/Chicago', name: 'Chicago (Central)', region: 'Americas', country: 'United States' },
  { id: 'America/Denver', name: 'Denver (Mountain)', region: 'Americas', country: 'United States' },
  { id: 'America/Los_Angeles', name: 'Los Angeles (Pacific)', region: 'Americas', country: 'United States' },
  { id: 'America/Anchorage', name: 'Anchorage (Alaska)', region: 'Americas', country: 'United States' },
  { id: 'Pacific/Honolulu', name: 'Honolulu (Hawaii)', region: 'Americas', country: 'United States' },
  { id: 'America/Phoenix', name: 'Phoenix (MST - No DST)', region: 'Americas', country: 'United States' },
  { id: 'America/Toronto', name: 'Toronto', region: 'Americas', country: 'Canada' },
  { id: 'America/Vancouver', name: 'Vancouver', region: 'Americas', country: 'Canada' },
  { id: 'America/Mexico_City', name: 'Mexico City', region: 'Americas', country: 'Mexico' },
  { id: 'America/Bogota', name: 'Bogotá', region: 'Americas', country: 'Colombia' },
  { id: 'America/Lima', name: 'Lima', region: 'Americas', country: 'Peru' },
  { id: 'America/Santiago', name: 'Santiago', region: 'Americas', country: 'Chile' },
  { id: 'America/Buenos_Aires', name: 'Buenos Aires', region: 'Americas', country: 'Argentina' },
  { id: 'America/Sao_Paulo', name: 'São Paulo', region: 'Americas', country: 'Brazil' },
  { id: 'Europe/London', name: 'London (GMT/BST)', region: 'Europe', country: 'United Kingdom' },
  { id: 'Europe/Dublin', name: 'Dublin', region: 'Europe', country: 'Ireland' },
  { id: 'Europe/Paris', name: 'Paris', region: 'Europe', country: 'France' },
  { id: 'Europe/Berlin', name: 'Berlin', region: 'Europe', country: 'Germany' },
  { id: 'Europe/Madrid', name: 'Madrid', region: 'Europe', country: 'Spain' },
  { id: 'Europe/Rome', name: 'Rome', region: 'Europe', country: 'Italy' },
  { id: 'Europe/Amsterdam', name: 'Amsterdam', region: 'Europe', country: 'Netherlands' },
  { id: 'Europe/Brussels', name: 'Brussels', region: 'Europe', country: 'Belgium' },
  { id: 'Europe/Zurich', name: 'Zurich', region: 'Europe', country: 'Switzerland' },
  { id: 'Europe/Vienna', name: 'Vienna', region: 'Europe', country: 'Austria' },
  { id: 'Europe/Stockholm', name: 'Stockholm', region: 'Europe', country: 'Sweden' },
  { id: 'Europe/Oslo', name: 'Oslo', region: 'Europe', country: 'Norway' },
  { id: 'Europe/Copenhagen', name: 'Copenhagen', region: 'Europe', country: 'Denmark' },
  { id: 'Europe/Helsinki', name: 'Helsinki', region: 'Europe', country: 'Finland' },
  { id: 'Europe/Warsaw', name: 'Warsaw', region: 'Europe', country: 'Poland' },
  { id: 'Europe/Prague', name: 'Prague', region: 'Europe', country: 'Czechia' },
  { id: 'Europe/Athens', name: 'Athens', region: 'Europe', country: 'Greece' },
  { id: 'Europe/Bucharest', name: 'Bucharest', region: 'Europe', country: 'Romania' },
  { id: 'Europe/Kyiv', name: 'Kyiv', region: 'Europe', country: 'Ukraine' },
  { id: 'Europe/Istanbul', name: 'Istanbul', region: 'Europe', country: 'Turkey' },
  { id: 'Europe/Moscow', name: 'Moscow', region: 'Europe', country: 'Russia' },
  { id: 'Asia/Dubai', name: 'Dubai (GST)', region: 'Asia', country: 'United Arab Emirates' },
  { id: 'Asia/Riyadh', name: 'Riyadh', region: 'Asia', country: 'Saudi Arabia' },
  { id: 'Asia/Kolkata', name: 'New Delhi / Mumbai (IST)', region: 'Asia', country: 'India' },
  { id: 'Asia/Bangkok', name: 'Bangkok (ICT)', region: 'Asia', country: 'Thailand' },
  { id: 'Asia/Jakarta', name: 'Jakarta (WIB)', region: 'Asia', country: 'Indonesia' },
  { id: 'Asia/Singapore', name: 'Singapore (SGT)', region: 'Asia', country: 'Singapore' },
  { id: 'Asia/Hong_Kong', name: 'Hong Kong (HKT)', region: 'Asia', country: 'Hong Kong' },
  { id: 'Asia/Shanghai', name: 'Beijing / Shanghai (CST)', region: 'Asia', country: 'China' },
  { id: 'Asia/Taipei', name: 'Taipei', region: 'Asia', country: 'Taiwan' },
  { id: 'Asia/Seoul', name: 'Seoul (KST)', region: 'Asia', country: 'South Korea' },
  { id: 'Asia/Tokyo', name: 'Tokyo (JST)', region: 'Asia', country: 'Japan' },
  { id: 'Australia/Perth', name: 'Perth (AWST)', region: 'Pacific', country: 'Australia' },
  { id: 'Australia/Adelaide', name: 'Adelaide (ACST)', region: 'Pacific', country: 'Australia' },
  { id: 'Australia/Sydney', name: 'Sydney (AEST)', region: 'Pacific', country: 'Australia' },
  { id: 'Australia/Melbourne', name: 'Melbourne (AEST)', region: 'Pacific', country: 'Australia' },
  { id: 'Australia/Brisbane', name: 'Brisbane (AEST - No DST)', region: 'Pacific', country: 'Australia' },
  { id: 'Pacific/Auckland', name: 'Auckland / Wellington', region: 'Pacific', country: 'New Zealand' },
  { id: 'Pacific/Fiji', name: 'Fiji', region: 'Pacific', country: 'Fiji' },
  { id: 'Pacific/Guam', name: 'Guam', region: 'Pacific', country: 'Guam' },
];

export async function openTimezoneModal() {
  if (typeof window.openManagementWindow === 'function') {
    window.openManagementWindow('mgmt-sec-wallpaper', 'mgmt-pane-language');
  }
  // The pop-up is part of Mission Control's markup, inserted when first needed (FE-04)
  let modal = document.getElementById('modal-clock-timezone');
  if (!modal) {
    await ensureManagementDom();
    modal = document.getElementById('modal-clock-timezone');
  }
  if (!modal) return;

  setupTimezoneModalEvents();

  const cfg = _config || loadWidgetConfig();
  _tempSelectedTz = cfg.clockTimezone || 'auto';
  _tempSelectedFormat = cfg.clockFormat || state.clockFormat || '24';
  _tzSearchQuery = '';
  _tzActiveRegion = 'all';

  modal.classList.add('open');
  if (modal.classList.contains('smart-modal-backdrop') || modal.style.display === 'none') {
    modal.style.display = 'flex';
  }

  const searchInput = document.getElementById('tz-search-input');
  if (searchInput) searchInput.value = '';

  const pills = document.querySelectorAll('.tz-region-pill');
  pills.forEach((p) => p.classList.toggle('active', p.dataset.region === 'all'));

  updateTzModalPreview();
  renderTimezoneList();

  if (_tzPreviewTimer) clearInterval(_tzPreviewTimer);
  _tzPreviewTimer = setInterval(updateTzModalPreview, 1000);
}
window.openTimezoneModal = openTimezoneModal;

export function initTimezoneControls() {
  const modal = document.getElementById('modal-clock-timezone');
  if (!modal) return;

  setupTimezoneModalEvents();

  const cfg = _config || loadWidgetConfig();
  _tempSelectedTz = cfg.clockTimezone || 'auto';
  _tempSelectedFormat = cfg.clockFormat || state.clockFormat || '24';
  _tzSearchQuery = '';
  _tzActiveRegion = 'all';

  const searchInput = document.getElementById('tz-search-input');
  if (searchInput) searchInput.value = '';

  const pills = document.querySelectorAll('.tz-region-pill');
  pills.forEach((p) => p.classList.toggle('active', p.dataset.region === 'all'));

  updateTzModalPreview();
  renderTimezoneList();

  if (_tzPreviewTimer) clearInterval(_tzPreviewTimer);
  _tzPreviewTimer = setInterval(updateTzModalPreview, 1000);
}
window.initTimezoneControls = initTimezoneControls;

export function closeTimezoneModal() {
  const modal = document.getElementById('modal-clock-timezone');
  if (modal) {
    modal.classList.remove('open');
    if (modal.classList.contains('smart-modal-backdrop')) {
      modal.style.display = 'none';
    }
  }
  if (_tzPreviewTimer) {
    clearInterval(_tzPreviewTimer);
    _tzPreviewTimer = null;
  }
}
window.closeTimezoneModal = closeTimezoneModal;

export function updateTzModalPreview() {
  const timeEl = document.getElementById('modal-tz-preview-time');
  const secEl = document.getElementById('modal-tz-preview-sec');
  const ampmEl = document.getElementById('modal-tz-preview-ampm');
  const dateEl = document.getElementById('modal-tz-preview-date');
  const activePill = document.getElementById('modal-tz-active-pill');
  if (!timeEl) return;

  const now = new Date();
  const tz = _tempSelectedTz;
  const fmt12 = _tempSelectedFormat === '12';

  let hoursStr = '';
  let minutes = '';
  let seconds = '';
  let ampm = '';
  let tzAbbr = '';

  try {
    const opts = {
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
      hour12: fmt12,
    };
    if (tz && tz !== 'auto') opts.timeZone = tz;
    const parts = new Intl.DateTimeFormat('en-US', opts).formatToParts(now);
    for (const part of parts) {
      if (part.type === 'hour') hoursStr = part.value.padStart(2, '0');
      else if (part.type === 'minute') minutes = part.value.padStart(2, '0');
      else if (part.type === 'second') seconds = part.value.padStart(2, '0');
      else if (part.type === 'dayPeriod') ampm = part.value.toUpperCase();
    }
    if (fmt12 && hoursStr.startsWith('0')) {
      hoursStr = hoursStr.replace(/^0/, '');
    }
    if (tz && tz !== 'auto') {
      const tzPart = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'short' })
        .formatToParts(now)
        .find((p) => p.type === 'timeZoneName');
      if (tzPart) tzAbbr = tzPart.value;
    }
  } catch (e) {
    let hours = now.getHours();
    minutes = String(now.getMinutes()).padStart(2, '0');
    seconds = String(now.getSeconds()).padStart(2, '0');
    if (fmt12) {
      ampm = hours >= 12 ? 'PM' : 'AM';
      hours = hours % 12 || 12;
    }
    hoursStr = fmt12 ? String(hours) : String(hours).padStart(2, '0');
  }

  timeEl.textContent = `${hoursStr}:${minutes}`;
  if (secEl) secEl.textContent = `:${seconds}`;
  if (ampmEl) ampmEl.textContent = ampm;

  if (dateEl) {
    try {
      const dateOpts = { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' };
      if (tz && tz !== 'auto') dateOpts.timeZone = tz;
      dateEl.textContent = formatDate(now, dateOpts);
    } catch (e) {
      dateEl.textContent = now.toDateString();
    }
  }

  if (activePill) {
    if (tz === 'auto') {
      const localTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'System Local';
      activePill.textContent = `Local Time (${localTz})`;
    } else {
      activePill.textContent = `${tz} ${tzAbbr ? '(' + tzAbbr + ')' : ''}`;
    }
  }

  const btn12 = document.getElementById('btn-tz-fmt-12');
  const btn24 = document.getElementById('btn-tz-fmt-24');
  if (btn12 && btn24) {
    btn12.style.background = fmt12 ? 'var(--brand, #00f0ff)' : 'transparent';
    btn12.style.color = fmt12 ? '#000' : 'var(--zn-text-muted)';
    btn24.style.background = !fmt12 ? 'var(--brand, #00f0ff)' : 'transparent';
    btn24.style.color = !fmt12 ? '#000' : 'var(--zn-text-muted)';
  }
}

export function renderTimezoneList() {
  const container = document.getElementById('tz-items-list');
  if (!container) return;

  const q = (_tzSearchQuery || '').toLowerCase().trim();
  const region = _tzActiveRegion || 'all';

  let filtered = TIMEZONES_CATALOG.filter((tz) => {
    if (region !== 'all' && tz.region !== region) return false;
    if (q) {
      const matchName = tz.name.toLowerCase().includes(q);
      const matchId = tz.id.toLowerCase().includes(q);
      const matchCountry = tz.country.toLowerCase().includes(q);
      if (!matchName && !matchId && !matchCountry) return false;
    }
    return true;
  });

  const now = new Date();
  const is12H = _tempSelectedFormat === '12';

  let html = '';
  // Auto item at top
  const isAutoSelected = _tempSelectedTz === 'auto';
  const localIana = Intl.DateTimeFormat().resolvedOptions().timeZone || 'System Local';
  html += `
    <div class="tz-item-row ${isAutoSelected ? 'selected' : ''}" data-tz-id="auto">
      <div style="display: flex; align-items: center; gap: 10px;">
        <span style="font-size: 14px;">📍</span>
        <div>
          <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">Local System Timezone (Auto)</div>
          <div style="font-size: var(--zn-fs-xs); color: var(--muted);">${escapeHtml(localIana)}</div>
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 8px;">
        <span style="font-size: var(--zn-fs-xs); font-weight: 700; font-family: var(--font-mono, monospace); color: var(--lt-ink-brand, var(--brand, #00f0ff));">${isAutoSelected ? '✓ Active' : ''}</span>
      </div>
    </div>
  `;

  filtered.forEach((tz) => {
    const isSelected = _tempSelectedTz === tz.id;
    let timeStr = '--:--';
    let tzAbbr = '';
    try {
      const opts = { hour: 'numeric', minute: 'numeric', hour12: is12H, timeZone: tz.id };
      timeStr = new Intl.DateTimeFormat('en-US', opts).format(now);
      const tzPart = new Intl.DateTimeFormat('en-US', { timeZone: tz.id, timeZoneName: 'short' })
        .formatToParts(now)
        .find((p) => p.type === 'timeZoneName');
      if (tzPart) tzAbbr = tzPart.value;
    } catch (e) {}

    html += `
      <div class="tz-item-row ${isSelected ? 'selected' : ''}" data-tz-id="${escapeHtml(tz.id)}">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="font-size: 14px;">🌐</span>
          <div>
            <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">${escapeHtml(tz.name)}</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted);">${escapeHtml(tz.id)} • ${escapeHtml(tz.country)}</div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="font-size: var(--zn-fs-xs); color: var(--zn-text-muted); font-family: var(--font-mono, monospace);">${escapeHtml(tzAbbr)}</span>
          <span style="font-size: var(--zn-fs-xs); font-weight: 700; font-family: var(--font-mono, monospace); color: ${isSelected ? 'var(--lt-ink-brand, var(--brand, #00f0ff))' : 'var(--zn-text)'};">${escapeHtml(timeStr)}</span>
          <span style="font-size: var(--zn-fs-xs); color: var(--lt-ink-brand, var(--brand, #00f0ff));">${isSelected ? '✓' : ''}</span>
        </div>
      </div>
    `;
  });

  if (!filtered.length && q) {
    html = `<div style="text-align: center; color: var(--muted); padding: 25px; font-size: var(--zn-fs-xs);">No matching timezones found for "${escapeHtml(q)}". Try custom IANA below.</div>`;
  }

  container.innerHTML = html;
}

export function setupTimezoneModalEvents() {
  const modal = document.getElementById('modal-clock-timezone');
  if (!modal || modal.dataset.eventsBound) return;
  modal.dataset.eventsBound = '1';

  const win = modal.querySelector('.smart-modal-window');
  const hdr = modal.querySelector('.smart-modal-header');
  if (win && hdr && typeof makeDraggable === 'function') {
    try {
      makeDraggable(win, hdr);
    } catch (e) {}
  }

  const closeBtn = document.getElementById('modal-clock-tz-close-btn');
  const cancelBtn = document.getElementById('modal-clock-tz-cancel-btn');
  const saveBtn = document.getElementById('modal-clock-tz-save-btn');
  const useBrowserBtn = document.getElementById('btn-tz-use-browser');
  const searchInput = document.getElementById('tz-search-input');
  const customInput = document.getElementById('tz-custom-input');
  const applyCustomBtn = document.getElementById('btn-tz-apply-custom');
  const btn12 = document.getElementById('btn-tz-fmt-12');
  const btn24 = document.getElementById('btn-tz-fmt-24');
  const listContainer = document.getElementById('tz-items-list');

  if (closeBtn) closeBtn.addEventListener('click', closeTimezoneModal);
  if (cancelBtn) cancelBtn.addEventListener('click', closeTimezoneModal);

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeTimezoneModal();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && (modal.classList.contains('open') || modal.style.display === 'flex')) {
      closeTimezoneModal();
    }
  });

  if (btn12) {
    btn12.addEventListener('click', () => {
      _tempSelectedFormat = '12';
      updateTzModalPreview();
      renderTimezoneList();
    });
  }
  if (btn24) {
    btn24.addEventListener('click', () => {
      _tempSelectedFormat = '24';
      updateTzModalPreview();
      renderTimezoneList();
    });
  }

  if (useBrowserBtn) {
    useBrowserBtn.addEventListener('click', () => {
      _tempSelectedTz = 'auto';
      updateTzModalPreview();
      renderTimezoneList();
    });
  }

  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      _tzSearchQuery = e.target.value;
      renderTimezoneList();
    });
  }

  const pills = document.querySelectorAll('.tz-region-pill');
  pills.forEach((p) => {
    p.addEventListener('click', () => {
      pills.forEach((el) => el.classList.remove('active'));
      p.classList.add('active');
      _tzActiveRegion = p.dataset.region || 'all';
      renderTimezoneList();
    });
  });

  if (listContainer) {
    listContainer.addEventListener('click', (e) => {
      const row = e.target.closest('.tz-item-row');
      if (!row || !row.dataset.tzId) return;
      _tempSelectedTz = row.dataset.tzId;
      updateTzModalPreview();
      renderTimezoneList();
    });
  }

  if (applyCustomBtn && customInput) {
    applyCustomBtn.addEventListener('click', () => {
      const val = customInput.value.trim();
      if (!val) return;
      try {
        new Intl.DateTimeFormat(undefined, { timeZone: val });
        _tempSelectedTz = val;
        updateTzModalPreview();
        renderTimezoneList();
        showToast(t('toast.selected_custom_timezone', 'Selected custom timezone: {val}', { val: val }), 'info');
      } catch (err) {
        showToast(t('toast.invalid_iana_timezone_example_america_toronto', 'Invalid IANA timezone: "{val}". Example: America/Toronto', { val: val }), 'error');
      }
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener('click', () => {
      saveWidgetConfig({
        clockTimezone: _tempSelectedTz,
        clockFormat: _tempSelectedFormat,
      });
      updateClock();
      const tzName = _tempSelectedTz === 'auto' ? 'Local System Time' : _tempSelectedTz;
      const msg = (t('tz.updated_toast') || 'Timezone updated to {tz}').replace('{tz}', tzName);
      showToast(msg, 'success');
      closeTimezoneModal();
    });
  }
}

/* =========================================================================
   Calendar, Day Agenda, Reminders & Provider Sync Modal Logic
   ========================================================================= */

export async function fetchCalendarEvents(startDate, endDate) {
  try {
    let url = '/api/calendar/events';
    if (startDate && endDate) url += `?start_date=${startDate}&end_date=${endDate}`;
    const data = await api.get(url);
    if (data && Array.isArray(data.events)) {
      _calendarEventsMap = {};
      data.events.forEach((ev) => {
        if (!ev.date) return;
        if (!_calendarEventsMap[ev.date]) _calendarEventsMap[ev.date] = [];
        _calendarEventsMap[ev.date].push(ev);
      });
      renderCalendar();
      if (document.getElementById('modal-calendar-notes')?.style.display !== 'none') {
        renderModalCalendarGrid();
        if (_modalCalSelectedDateKey) renderDayAgenda(_modalCalSelectedDateKey);
      }
    }
  } catch (err) {
    console.warn('Failed to fetch calendar events:', err);
  }
}
window.fetchCalendarEvents = fetchCalendarEvents;

export async function fetchCalendarFeeds() {
  try {
    const data = await api.get('/api/calendar/feeds');
    if (data && Array.isArray(data.feeds)) {
      _calendarFeeds = data.feeds;
      renderFeedsList();
    }
  } catch (err) {
    console.warn('Failed to fetch calendar feeds:', err);
  }
}
window.fetchCalendarFeeds = fetchCalendarFeeds;

export async function openCalendarModal(initialDateKey) {
  if (typeof window.openManagementWindow === 'function') {
    window.openManagementWindow('mgmt-sec-wallpaper', 'mgmt-pane-calendar');
  }
  // The pop-up is part of Mission Control's markup, inserted when first needed (FE-04)
  let modal = document.getElementById('modal-calendar-notes');
  if (!modal) {
    await ensureManagementDom();
    modal = document.getElementById('modal-calendar-notes');
  }
  if (!modal) return;

  setupCalendarModalEvents();

  const now = new Date();
  if (initialDateKey && /^\d{4}-\d{2}-\d{2}$/.test(initialDateKey)) {
    const [y, m, d] = initialDateKey.split('-').map(Number);
    _modalCalDate = new Date(y, m - 1, d);
    _modalCalSelectedDateKey = initialDateKey;
  } else {
    _modalCalDate = new Date();
    _modalCalSelectedDateKey = toDateKey(now.getFullYear(), now.getMonth(), now.getDate());
  }

  modal.classList.add('open');
  if (modal.classList.contains('smart-modal-backdrop') || modal.style.display === 'none') {
    modal.style.display = 'flex';
  }

  renderModalCalendarGrid();
  renderDayAgenda(_modalCalSelectedDateKey);

  // Fetch feeds and events for the current month
  fetchCalendarFeeds();
  const year = _modalCalDate.getFullYear();
  const month = _modalCalDate.getMonth();
  const startD = toDateKey(year, month - 1, 1);
  const endD = toDateKey(year, month + 1, 28);
  fetchCalendarEvents(startD, endD);
}
window.openCalendarModal = openCalendarModal;

export function initCalendarView(initialDateKey) {
  const modal = document.getElementById('modal-calendar-notes');
  if (!modal) return;

  setupCalendarModalEvents();

  const now = new Date();
  if (initialDateKey && /^\d{4}-\d{2}-\d{2}$/.test(initialDateKey)) {
    const [y, m, d] = initialDateKey.split('-').map(Number);
    _modalCalDate = new Date(y, m - 1, d);
    _modalCalSelectedDateKey = initialDateKey;
  } else {
    _modalCalDate = new Date();
    _modalCalSelectedDateKey = toDateKey(now.getFullYear(), now.getMonth(), now.getDate());
  }

  renderModalCalendarGrid();
  renderDayAgenda(_modalCalSelectedDateKey);

  fetchCalendarFeeds();
  const year = _modalCalDate.getFullYear();
  const month = _modalCalDate.getMonth();
  const startD = toDateKey(year, month - 1, 1);
  const endD = toDateKey(year, month + 1, 28);
  fetchCalendarEvents(startD, endD);
}
window.initCalendarView = initCalendarView;

export function closeCalendarModal() {
  const modal = document.getElementById('modal-calendar-notes');
  if (modal) {
    modal.classList.remove('open');
    if (modal.classList.contains('smart-modal-backdrop')) {
      modal.style.display = 'none';
    }
  }
  renderCalendar();
}
window.closeCalendarModal = closeCalendarModal;

export function renderModalCalendarGrid() {
  const grid = document.getElementById('modal-cal-grid');
  const titleEl = document.getElementById('modal-cal-month-title');
  if (!grid) return;

  const year = _modalCalDate.getFullYear();
  const month = _modalCalDate.getMonth();
  const today = new Date();

  if (titleEl) {
    const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    titleEl.textContent = `${monthNames[month]} ${year}`;
  }

  const country = getActiveCountry();
  const holidaysYear = getHolidaysForYear(year, country);

  const prevMonthDate = new Date(year, month - 1, 1);
  const prevYear = prevMonthDate.getFullYear();
  const prevMonthIdx = prevMonthDate.getMonth();
  const prevHolidaysYear = prevYear !== year ? getHolidaysForYear(prevYear, country) : holidaysYear;

  const nextMonthDate = new Date(year, month + 1, 1);
  const nextYear = nextMonthDate.getFullYear();
  const nextMonthIdx = nextMonthDate.getMonth();
  const nextHolidaysYear = nextYear !== year ? getHolidaysForYear(nextYear, country) : holidaysYear;

  const firstDay = new Date(year, month, 1).getDay(); // 0 is Sun
  const totalDays = new Date(year, month + 1, 0).getDate();
  const prevMonthTotalDays = new Date(year, month, 0).getDate();

  let html = '';
  const weekdays = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
  weekdays.forEach((d) => {
    html += `<div class="cal-weekday">${d}</div>`;
  });

  // Previous month days
  for (let i = firstDay - 1; i >= 0; i--) {
    const d = prevMonthTotalDays - i;
    const key = toDateKey(prevYear, prevMonthIdx, d);
    const holidayList = prevHolidaysYear[key];
    const isHoliday = !!holidayList && holidayList.length > 0;
    const isSelected = key === _modalCalSelectedDateKey;
    const dayEvents = _calendarEventsMap[key] || [];

    let cls = 'cal-day cal-other-month';
    if (isSelected) cls += ' cal-selected';
    if (isHoliday) cls += ' cal-holiday';
    if (dayEvents.length > 0) {
      cls += ' has-notes';
      if (dayEvents.some((e) => e.type === 'task')) cls += ' has-task';
    }
    html += `<div class="${cls}" data-date-key="${key}">${d}</div>`;
  }

  // Current month days
  for (let d = 1; d <= totalDays; d++) {
    const key = toDateKey(year, month, d);
    const isToday = today.getFullYear() === year && today.getMonth() === month && today.getDate() === d;
    const isSelected = key === _modalCalSelectedDateKey;
    const holidayList = holidaysYear[key];
    const isHoliday = !!holidayList && holidayList.length > 0;
    const dayEvents = _calendarEventsMap[key] || [];

    let cls = 'cal-day';
    if (isToday) cls += ' cal-today';
    if (isSelected) cls += ' cal-selected';
    if (isHoliday) cls += ' cal-holiday';
    if (dayEvents.length > 0) {
      cls += ' has-notes';
      if (dayEvents.some((e) => e.type === 'task')) cls += ' has-task';
    }
    html += `<div class="${cls}" data-date-key="${key}">${d}</div>`;
  }

  // Next month days
  const cellsRendered = firstDay + totalDays;
  const nextMonthPadding = (7 - (cellsRendered % 7)) % 7;
  for (let d = 1; d <= nextMonthPadding; d++) {
    const key = toDateKey(nextYear, nextMonthIdx, d);
    const holidayList = nextHolidaysYear[key];
    const isHoliday = !!holidayList && holidayList.length > 0;
    const isSelected = key === _modalCalSelectedDateKey;
    const dayEvents = _calendarEventsMap[key] || [];

    let cls = 'cal-day cal-other-month';
    if (isSelected) cls += ' cal-selected';
    if (isHoliday) cls += ' cal-holiday';
    if (dayEvents.length > 0) {
      cls += ' has-notes';
      if (dayEvents.some((e) => e.type === 'task')) cls += ' has-task';
    }
    html += `<div class="${cls}" data-date-key="${key}">${d}</div>`;
  }

  grid.innerHTML = html;
}

export function renderDayAgenda(dateKey) {
  _modalCalSelectedDateKey = dateKey;
  const titleEl = document.getElementById('modal-cal-selected-date-str');
  const subEl = document.getElementById('modal-cal-selected-sub');
  const listEl = document.getElementById('modal-cal-agenda-list');
  if (!listEl) return;

  // Format date nicely
  try {
    const [y, m, d] = dateKey.split('-').map(Number);
    const parsedDate = new Date(y, m - 1, d);
    const formattedDate = new Intl.DateTimeFormat([], {
      weekday: 'long',
      month: 'long',
      day: 'numeric',
      year: 'numeric',
    }).format(parsedDate);
    if (titleEl) titleEl.textContent = formattedDate;
  } catch (e) {
    if (titleEl) titleEl.textContent = dateKey;
  }

  const allItems = _calendarEventsMap[dateKey] || [];
  const filter = _calActiveFilter || 'all';

  let items = allItems.filter((item) => {
    if (filter === 'all') return true;
    if (filter === 'synced') return item.source === 'synced';
    return item.type === filter;
  });

  if (subEl) {
    subEl.textContent = `${allItems.length} item(s) on agenda for this day`;
  }

  // Check holiday for this day
  const [y, m, d] = dateKey.split('-').map(Number);
  const country = getActiveCountry();
  const holidays = getHolidaysForYear(y, country)[dateKey] || [];

  let html = '';

  if (holidays.length > 0) {
    const hNames = holidays.map((h) => h.name || h.localName).join(' / ');
    html += `
      <div style="background: rgba(236,72,153,0.12); border: 1px solid rgba(236,72,153,0.3); border-radius: 8px; padding: 10px 14px; display: flex; align-items: center; gap: 10px;">
        <span style="font-size: 16px;">🎉</span>
        <div>
          <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--lt-t-f472b6ff, #f472b6);">Official Holiday: ${escapeHtml(hNames)}</div>
          <div style="font-size: var(--zn-fs-xs); color: var(--muted);">${escapeHtml(country)} Public Holiday</div>
        </div>
      </div>
    `;
  }

  if (!items.length) {
    html += `
      <div style="text-align: center; color: var(--muted); padding: 40px 20px; font-size: var(--zn-fs-xs);">
        <div style="font-size: 26px; margin-bottom: 8px;">📝</div>
        <div style="font-weight: 600; color: var(--zn-text-soft);">${t('cal.empty_agenda') || 'No notes or reminders for this day.'}</div>
        <div style="font-size: var(--zn-fs-xs); margin-top: 4px;">Use the composer above to add a task, reminder, or note.</div>
      </div>
    `;
  } else {
    items.forEach((item) => {
      const isTask = item.type === 'task';
      const isCompleted = !!item.completed;
      const isSynced = item.source === 'synced';
      const timeStr = item.time || '';
      const category = item.category || 'General';

      let typeIcon = '📝';
      if (item.type === 'reminder') typeIcon = '⏰';
      else if (item.type === 'task') typeIcon = '📋';
      else if (item.type === 'event') typeIcon = '📅';
      if (isSynced) typeIcon = '🌐';

      html += `
        <div class="cal-agenda-card ${isCompleted ? 'completed' : ''}" data-item-id="${escapeHtml(item.id || '')}">
          ${
            isTask
              ? `<input type="checkbox" class="cal-task-check" ${isCompleted ? 'checked' : ''} style="margin-top: 3px; cursor: pointer; accent-color: var(--ok2, #25c2a0); width: 15px; height: 15px;" />`
              : `<span style="font-size: 15px; margin-top: 1px;">${typeIcon}</span>`
          }
          <div style="flex: 1; display: flex; flex-direction: column; gap: 3px;">
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
              <span class="cal-agenda-title" style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">${escapeHtml(item.title)}</span>
              <div style="display: flex; align-items: center; gap: 6px;">
                ${timeStr ? `<span style="font-size: var(--zn-fs-xs); font-weight: 700; font-family: var(--font-mono, monospace); background: var(--zn-glaze-8); padding: 2px 6px; border-radius: 4px; color: var(--lt-ink-brand, var(--brand, #00f0ff));">${escapeHtml(timeStr)}</span>` : ''}
                ${isSynced ? `<span style="font-size: var(--zn-fs-xs); font-weight: 700; background: rgba(234,179,8,0.15); border: 1px solid rgba(234,179,8,0.3); color: var(--lt-t-eab308ff, #eab308); padding: 2px 6px; border-radius: 4px;">${escapeHtml(item.feed_name || 'Synced')}</span>` : `<span style="font-size: var(--zn-fs-xs); color: var(--muted); background: var(--zn-glaze-5); padding: 2px 6px; border-radius: 4px;">${escapeHtml(category)}</span>`}
                ${
                  !isSynced
                    ? `<button type="button" class="btn-cal-delete-note btn-icon" style="background: transparent; border: none; color: var(--lt-t-ef4444ff, #ef4444); opacity: 0.7; cursor: pointer; font-size: var(--zn-fs-xs); padding: 2px 4px;" title="${t('ui.delete_note', 'Delete Note')}">🗑️</button>`
                    : ''
                }
              </div>
            </div>
            ${item.description ? `<div style="font-size: var(--zn-fs-xs); color: var(--muted); line-height: 1.3;">${escapeHtml(item.description)}</div>` : ''}
          </div>
        </div>
      `;
    });
  }

  listEl.innerHTML = html;
}

export function renderFeedsList() {
  const container = document.getElementById('cal-feeds-list');
  if (!container) return;

  if (!_calendarFeeds.length) {
    container.innerHTML = `
      <div style="font-size: var(--zn-fs-xs); color: var(--muted); text-align: center; padding: 10px;">
        No external calendar feeds synced. Click "+ Add Feed" to connect Google Calendar or Apple iCal.
      </div>
    `;
    return;
  }

  let html = '';
  _calendarFeeds.forEach((feed) => {
    html += `
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-8); border-radius: 6px;" data-feed-id="${escapeHtml(feed.id)}">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="width: 8px; height: 8px; border-radius: 50%; background: ${escapeHtml(feed.color || '#38bdf8')};"></span>
          <div>
            <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">${escapeHtml(feed.name)}</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted);">${feed.event_count || 0} events • ${escapeHtml(feed.provider || 'iCal')}</div>
          </div>
        </div>
        <button type="button" class="btn-cal-delete-feed btn-icon" style="background: transparent; border: none; color: var(--lt-t-ef4444ff, #ef4444); opacity: 0.7; cursor: pointer; font-size: var(--zn-fs-xs); padding: 2px;" title="${t('ui.delete_feed', 'Delete Feed')}">🗑️</button>
      </div>
    `;
  });
  container.innerHTML = html;
}

export async function exportCalendarIcs() {
  try {
    const token = auth.getToken();
    const res = await fetch('/api/calendar/export', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error('Failed to export calendar');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `zettnas_calendar_${new Date().toISOString().split('T')[0]}.ics`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast(t('toast.calendar_exported_ics', 'Calendar exported (.ics)'), 'success');
  } catch (err) {
    showToast(t('toast.failed_export_calendar', 'Failed to export calendar: {error}', { error: err.message }), 'error');
  }
}
window.exportCalendarIcs = exportCalendarIcs;

export function setupCalendarModalEvents() {
  const modal = document.getElementById('modal-calendar-notes');
  if (!modal || modal.dataset.eventsBound) return;
  modal.dataset.eventsBound = '1';

  const win = modal.querySelector('.smart-modal-window');
  const hdr = modal.querySelector('.smart-modal-header');
  if (win && hdr && typeof makeDraggable === 'function') {
    try {
      makeDraggable(win, hdr);
    } catch (e) {}
  }

  const closeBtn = document.getElementById('modal-cal-notes-close-btn');
  const syncBtn = document.getElementById('btn-cal-sync-now');
  const exportBtn = document.getElementById('btn-cal-export-ics');
  const prevBtn = document.getElementById('btn-modal-cal-prev');
  const nextBtn = document.getElementById('btn-modal-cal-next');
  const todayBtn = document.getElementById('btn-modal-cal-today');
  const grid = document.getElementById('modal-cal-grid');
  const agendaList = document.getElementById('modal-cal-agenda-list');
  const saveNoteBtn = document.getElementById('btn-cal-save-note');
  const toggleFeedBtn = document.getElementById('btn-toggle-add-feed');
  const cancelFeedBtn = document.getElementById('btn-cancel-add-feed');
  const submitFeedBtn = document.getElementById('btn-submit-add-feed');
  const addFeedForm = document.getElementById('cal-add-feed-form');
  const feedsList = document.getElementById('cal-feeds-list');

  if (closeBtn) closeBtn.addEventListener('click', closeCalendarModal);

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeCalendarModal();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && (modal.classList.contains('open') || modal.style.display === 'flex')) {
      closeCalendarModal();
    }
  });

  if (prevBtn) {
    prevBtn.addEventListener('click', () => {
      _modalCalDate.setMonth(_modalCalDate.getMonth() - 1);
      renderModalCalendarGrid();
      const y = _modalCalDate.getFullYear();
      const m = _modalCalDate.getMonth();
      fetchCalendarEvents(toDateKey(y, m - 1, 1), toDateKey(y, m + 1, 28));
    });
  }

  if (nextBtn) {
    nextBtn.addEventListener('click', () => {
      _modalCalDate.setMonth(_modalCalDate.getMonth() + 1);
      renderModalCalendarGrid();
      const y = _modalCalDate.getFullYear();
      const m = _modalCalDate.getMonth();
      fetchCalendarEvents(toDateKey(y, m - 1, 1), toDateKey(y, m + 1, 28));
    });
  }

  if (todayBtn) {
    todayBtn.addEventListener('click', () => {
      const now = new Date();
      _modalCalDate = new Date();
      _modalCalSelectedDateKey = toDateKey(now.getFullYear(), now.getMonth(), now.getDate());
      renderModalCalendarGrid();
      renderDayAgenda(_modalCalSelectedDateKey);
      fetchCalendarEvents();
    });
  }

  if (grid) {
    grid.addEventListener('click', (e) => {
      const cell = e.target.closest('.cal-day');
      if (!cell || !cell.dataset.dateKey) return;
      _modalCalSelectedDateKey = cell.dataset.dateKey;
      renderModalCalendarGrid();
      renderDayAgenda(_modalCalSelectedDateKey);
    });
  }

  // Filter pills
  const filterPills = modal.querySelectorAll('.cal-filter-pill');
  filterPills.forEach((p) => {
    p.addEventListener('click', () => {
      filterPills.forEach((el) => el.classList.remove('active'));
      p.classList.add('active');
      _calActiveFilter = p.dataset.filter || 'all';
      if (_modalCalSelectedDateKey) renderDayAgenda(_modalCalSelectedDateKey);
    });
  });

  // Add Note composer
  if (saveNoteBtn) {
    saveNoteBtn.addEventListener('click', async () => {
      const titleInput = document.getElementById('cal-new-note-title');
      const timeInput = document.getElementById('cal-new-note-time');
      const typeSelect = document.getElementById('cal-new-note-type');
      const descInput = document.getElementById('cal-new-note-desc');
      const catInput = document.getElementById('cal-new-note-category');

      const title = titleInput?.value?.trim();
      if (!title) {
        showToast(t('toast.please_enter_a_title_for_the', 'Please enter a title for the note/reminder'), 'warning');
        if (titleInput) titleInput.focus();
        return;
      }

      const payload = {
        date: _modalCalSelectedDateKey,
        time: timeInput?.value || '',
        title: title,
        type: typeSelect?.value || 'note',
        description: descInput?.value?.trim() || '',
        category: catInput?.value?.trim() || 'General',
        completed: false,
      };

      try {
        const res = await api.post('/api/calendar/notes', payload);
        if (res && res.note) {
          if (!_calendarEventsMap[_modalCalSelectedDateKey]) {
            _calendarEventsMap[_modalCalSelectedDateKey] = [];
          }
          _calendarEventsMap[_modalCalSelectedDateKey].push(res.note);
          if (titleInput) titleInput.value = '';
          if (descInput) descInput.value = '';
          renderModalCalendarGrid();
          renderDayAgenda(_modalCalSelectedDateKey);
          renderCalendar();
          showToast(t('cal.note_added') || 'Note added successfully', 'success');
        }
      } catch (err) {
        showToast(t('toast.failed_add_note', 'Failed to add note: {error}', { error: err.message }), 'error');
      }
    });
  }

  // Task complete checkbox & Note delete in Agenda List
  if (agendaList) {
    agendaList.addEventListener('click', async (e) => {
      const card = e.target.closest('.cal-agenda-card');
      if (!card || !card.dataset.itemId) return;
      const itemId = card.dataset.itemId;

      // Delete note
      if (e.target.closest('.btn-cal-delete-note')) {
        try {
          await api.delete(`/api/calendar/notes/${itemId}`);
          if (_calendarEventsMap[_modalCalSelectedDateKey]) {
            _calendarEventsMap[_modalCalSelectedDateKey] = _calendarEventsMap[_modalCalSelectedDateKey].filter(
              (item) => item.id !== itemId
            );
          }
          renderModalCalendarGrid();
          renderDayAgenda(_modalCalSelectedDateKey);
          renderCalendar();
          showToast(t('toast.note_deleted', 'Note deleted'), 'info');
        } catch (err) {
          showToast(t('toast.failed_delete_note', 'Failed to delete note: {error}', { error: err.message }), 'error');
        }
        return;
      }

      // Toggle Task Checkbox
      if (e.target.classList.contains('cal-task-check')) {
        const checked = e.target.checked;
        try {
          await api.patch(`/api/calendar/notes/${itemId}`, { completed: checked });
          const items = _calendarEventsMap[_modalCalSelectedDateKey] || [];
          const item = items.find((i) => i.id === itemId);
          if (item) item.completed = checked;
          card.classList.toggle('completed', checked);
        } catch (err) {
          e.target.checked = !checked;
          showToast(t('toast.failed_update_task', 'Failed to update task: {error}', { error: err.message }), 'error');
        }
      }
    });
  }

  // Toggle Add Feed Drawer
  if (toggleFeedBtn && addFeedForm) {
    toggleFeedBtn.addEventListener('click', () => {
      const isHidden = addFeedForm.style.display === 'none';
      addFeedForm.style.display = isHidden ? 'flex' : 'none';
    });
  }
  if (cancelFeedBtn && addFeedForm) {
    cancelFeedBtn.addEventListener('click', () => {
      addFeedForm.style.display = 'none';
    });
  }

  // Submit Add Feed Form
  if (submitFeedBtn) {
    submitFeedBtn.addEventListener('click', async () => {
      const nameInput = document.getElementById('cal-feed-name-input');
      const urlInput = document.getElementById('cal-feed-url-input');
      const colorSelect = document.getElementById('cal-feed-color-select');

      const name = nameInput?.value?.trim();
      const url = urlInput?.value?.trim();
      if (!name || !url) {
        showToast(t('toast.please_enter_feed_name_and_valid', 'Please enter feed name and valid iCal (.ics) URL'), 'warning');
        return;
      }

      try {
        submitFeedBtn.disabled = true;
        submitFeedBtn.textContent = t('ui.connecting', 'Connecting...');
        const res = await api.post('/api/calendar/feeds', {
          name,
          url,
          color: colorSelect?.value || '#38bdf8',
          provider: 'google',
          enabled: true,
        });

        if (res && res.status === 'ok') {
          showToast(t('toast.connected_events_synced', 'Connected {name} ({event_count} events synced)', { name: name, event_count: res.event_count || 0 }), 'success');
          if (nameInput) nameInput.value = '';
          if (urlInput) urlInput.value = '';
          if (addFeedForm) addFeedForm.style.display = 'none';
          fetchCalendarFeeds();
          fetchCalendarEvents();
        }
      } catch (err) {
        showToast(t('toast.failed_connect_feed', 'Failed to connect feed: {error}', { error: err.body?.detail || err.message }), 'error');
      } finally {
        submitFeedBtn.disabled = false;
        submitFeedBtn.textContent = t('ui.connect_sync', 'Connect & Sync');
      }
    });
  }

  // Delete feed
  if (feedsList) {
    feedsList.addEventListener('click', async (e) => {
      const delBtn = e.target.closest('.btn-cal-delete-feed');
      if (!delBtn) return;
      const row = delBtn.closest('[data-feed-id]');
      if (!row || !row.dataset.feedId) return;
      const feedId = row.dataset.feedId;

      try {
        await api.delete(`/api/calendar/feeds/${feedId}`);
        showToast(t('toast.calendar_feed_removed', 'Calendar feed removed'), 'info');
        fetchCalendarFeeds();
        fetchCalendarEvents();
      } catch (err) {
        showToast(t('toast.failed_delete_feed', 'Failed to delete feed: {error}', { error: err.message }), 'error');
      }
    });
  }

  // Sync Feeds Now
  if (syncBtn) {
    syncBtn.addEventListener('click', async () => {
      try {
        syncBtn.disabled = true;
        syncBtn.textContent = t('ui.syncing', 'Syncing...');
        const res = await api.post('/api/calendar/sync');
        if (res && res.status === 'ok') {
          showToast(t('toast.synced_feed_s_with_event_s', 'Synced {synced_feeds} feed(s) with {total_events} event(s)', { synced_feeds: res.synced_feeds, total_events: res.total_events }), 'success');
          fetchCalendarFeeds();
          fetchCalendarEvents();
        }
      } catch (err) {
        showToast(t('toast.sync_failed', 'Sync failed: {error}', { error: err.message }), 'error');
      } finally {
        syncBtn.disabled = false;
        syncBtn.innerHTML = '🔄 Sync Feeds';
      }
    });
  }

  // Export .ics
  if (exportBtn) {
    exportBtn.addEventListener('click', exportCalendarIcs);
  }
}

