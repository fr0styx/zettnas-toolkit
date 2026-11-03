/**
 * The header's LCD and live-data badges: their words, in the reader's language, and their colours.
 * Split out of main.js so they can be tested without starting the whole app (NUX-20).
 */
import { t } from './i18n.js';

/**
 * Shows what the front LCD is doing, from /api/lcd_status.
 * @param {HTMLElement | null} badge
 * @param {{enabled?: boolean, fb_present?: boolean, screen_off?: boolean, power?: boolean, active?: boolean, fps?: number}} data
 */
export function renderLcdBadge(badge, data) {
  if (!badge) return;
  let text, state, cls, title;
  if (!data.enabled) {
    text = t('lcd.badge_off_config', 'LCD: turned off');
    state = 'disabled';
    cls = 'disabled';
    title = t('ui.lcd_direct_output_is_disabled', 'LCD direct output is disabled in configuration.');
  } else if (!data.fb_present) {
    text = t('lcd.badge_none', 'LCD: not found');
    state = 'missing';
    cls = 'offline';
    title = t('ui.no_framebuffer_device_detected_at', 'No framebuffer device detected at /dev/fb0.');
  } else if (data.screen_off || data.power === false) {
    text = t('stg.lcd_badge_off', 'LCD: SCREEN OFF');
    cls = 'disabled';
    title = t('ui.physical_lcd_display_is_turned', 'Physical LCD display is turned off (0 FPS).');
  } else if (data.active) {
    text = t('lcd.badge_fps', 'LCD: {fps} FPS ACTIVE', { fps: data.fps });
    cls = 'active';
    title = t('lcd.badge_fps_title', 'LCD direct output is actively streaming at {fps} FPS.', { fps: data.fps });
  } else {
    text = t('lcd.badge_idle', 'LCD: IDLE');
    cls = 'offline';
    title = t('ui.lcd_renderer_process_is_offline', 'LCD renderer process is offline or initializing.');
  }
  badge.textContent = text;
  if (state) badge.dataset.lcdState = state;
  badge.className = 'lcd-status-badge lcd-status-' + cls;
  badge.title = title;
}

/**
 * Says whether the numbers arrive live (server-sent events) or by polling.
 * @param {HTMLElement | null} badge
 * @param {boolean} live
 */
export function renderStreamBadge(badge, live) {
  if (!badge) return;
  badge.textContent = live ? t('ui.stream_live', 'LIVE SSE') : t('ui.stream_polling', 'POLLING');
  badge.className = 'header-badge ' + (live ? 'active' : 'warning');
}
