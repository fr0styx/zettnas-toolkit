// What "Find this drive" says, once the server has answered (SET-09).
// The page used to beep, highlight the tile and say "pulsing … for 5s" before it had asked;
// the answer and any error were thrown away.

import { t } from '../i18n.js';

/**
 * @param {any} res the answer of POST /api/disk/locate
 * @param {string} dev the drive's name
 * @returns {{ text: string, tone: string, blinking: boolean }}
 */
export function locateSaid(res, dev) {
  const secs = Number(res?.duration) || 5;
  if (res?.success && res.method === 'bay_light') {
    return { text: t('locate.bay', 'The light of the bay that holds {dev} blinks for {secs} seconds.', { dev, secs }), tone: 'success', blinking: true };
  }
  if (res?.success) {
    return { text: t('locate.activity', 'The activity light of {dev} flickers for {secs} seconds. Look for the light that moves.', { dev, secs }), tone: 'success', blinking: true };
  }
  const why = res?.error || res?.detail || '';
  return {
    text: why ? t('locate.failed_why', 'No light could be blinked for {dev}: {why}', { dev, why }) : t('locate.failed', 'No light could be blinked for {dev}.', { dev }),
    tone: 'error',
    blinking: false,
  };
}
