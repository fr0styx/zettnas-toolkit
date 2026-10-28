/**
 * Desktop widget names, for the code that needs them before the widgets module loads
 * (the right-click menu). The widgets themselves load after the first paint (PERF-9).
 */
import { t } from '../i18n.js';

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

export function getWidgetDisplayName(widgetKey) {
  if (!widgetKey) return 'Widget';
  const i18nKey = `widget.${widgetKey}`;
  const translated = t(i18nKey);
  if (translated && translated !== i18nKey) return translated;
  return WIDGET_NAMES[widgetKey] || 'Widget';
}
