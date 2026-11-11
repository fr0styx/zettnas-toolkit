// One rule for "warm" and "too hot" (SET-09).
// The bay picture said amber at 46 °C and red at 53 °C for every drive; Drive Health said 50 and
// 60 °C for hard drives, 70 and 80 °C for NVMe; the alerts and the fans act at 50 and 55, 70 and
// 75. The same drive could be amber in one place and fine in the next. These are the limits the
// alerts and the fans use, for every place that colours a temperature.

export const LIMITS = { hdd: { warm: 50, hot: 55 }, nvme: { warm: 70, hot: 75 } };

/** Whether a drive record is an NVMe drive, whatever part of the server it came from. */
export function isNvmeDrive(d) {
  if (!d) return false;
  if (d.is_nvme === true) return true;
  return /^nv/i.test(String(d.dev || d.device || d.name || ''));
}

/**
 * "fine", "warm" or "hot" for a temperature, by the drive's kind.
 * @param {number | null | undefined} tempC
 * @param {boolean} [nvme]
 * @returns {'fine' | 'warm' | 'hot' | 'unknown'}
 */
export function tempLevel(tempC, nvme = false) {
  if (tempC == null || Number.isNaN(Number(tempC))) return 'unknown';
  const limits = nvme ? LIMITS.nvme : LIMITS.hdd;
  if (Number(tempC) >= limits.hot) return 'hot';
  if (Number(tempC) >= limits.warm) return 'warm';
  return 'fine';
}
