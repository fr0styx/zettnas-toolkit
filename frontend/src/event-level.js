/**
 * How an event's level is drawn (SET-03). The server sends info, success, warning, error and
 * critical. "critical" is its most serious level (a drive losing sectors, the ransomware guard
 * pausing all changes, a UPS shutting the NAS down); the log, the bell, the bell's preview and the
 * event dialog each had their own list of levels and none knew it, so it was drawn as plain
 * information and left out of the bell's "Errors" filter.
 */
export function eventLook(level) {
  const l = String(level || 'info').toLowerCase();
  if (l === 'critical' || l === 'crit' || l === 'error') return 'error';
  if (l === 'warning' || l === 'warn') return 'warning';
  if (l === 'success') return 'success';
  return 'info';
}
