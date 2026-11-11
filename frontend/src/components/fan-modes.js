/**
 * The fan modes in words, shared by the Host tab and the Fans tab (SET-15, Hardware 1). Quiet,
 * Balanced, Performance and Full are fixed speeds today (backend/services/fan_control.py: 67, 120,
 * 155 and 183 of 183): they do not follow the temperature, so choosing one asks first.
 */
import { t } from '../i18n.js';
import { showConfirmToast } from '../toast.js';

/** What each fixed mode runs at, in percent of full speed. */
export const FIXED_PCT = { quiet: 37, balanced: 66, performance: 85, full: 100 };

/** A mode's name: "Automatic", "Quiet · fixed 37 %", "Fixed 50 %" (set by hand). */
export function modeName(profile, manualPct) {
  const p = String(profile || '').toLowerCase();
  if (p === 'auto') return t('hw.mode_auto', 'Automatic');
  if (p === 'quiet') return t('hw.mode_quiet', 'Quiet · fixed {pct} %', { pct: FIXED_PCT.quiet });
  if (p === 'balanced') return t('hw.mode_balanced', 'Balanced · fixed {pct} %', { pct: FIXED_PCT.balanced });
  if (p === 'performance') return t('hw.mode_performance', 'Performance · fixed {pct} %', { pct: FIXED_PCT.performance });
  if (p === 'full') return t('hw.mode_full', 'Full speed');
  const pct = Number(manualPct);
  return Number.isFinite(pct) ? t('hw.mode_manual', 'Fixed {pct} %', { pct: Math.round(pct) }) : t('hw.mode_manual_any', 'Set by hand');
}

/** Asks before the fans run at a fixed speed; onYes runs only on a yes, onNo otherwise. */
export function askFixedSpeed(pct, onYes, onNo = null) {
  showConfirmToast(
    t('fan.fixed_title', 'Keep the fans at a fixed {pct} %?', { pct }),
    t('fan.fixed_msg', 'At a fixed speed the fans do not follow the temperature. They speed up only when a drive reaches 55 °C or the processor gets very hot. Automatic follows the temperature and is recommended.'),
    onYes,
    onNo,
    { okText: t('fan.fixed_ok', 'Use {pct} %', { pct }), cancelText: t('common.cancel', 'Cancel') }
  );
}
