/**
 * When to fetch the big windows ahead of use (NPERF-5). Mission Control, the File Explorer, the
 * settings drawer and the users code are fetched while the browser is idle so they open at
 * once; that is only worth it for someone signed in at the desktop. The sign-in screen, the
 * phone layout, the front screen and a VM console page don't fetch them: a phone on mobile data
 * would download about 250 kB it may never use. Opening a window still loads it on demand.
 */

/** True when someone is signed in and the desktop (not the phone layout) is showing. */
export function desktopUser(doc = document, flags = {}) {
  if (flags.lcd || flags.console) return false;
  return !doc.documentElement.classList.contains('auth-required') && !doc.body.classList.contains('phone-shell');
}

/**
 * Runs fn once, as soon as desktopUser() holds: now, or after signing in or leaving the phone
 * layout. Returns a function that stops waiting.
 */
export function forDesktopUser(fn, doc = document, flags = {}) {
  if (flags.lcd || flags.console) return () => {};
  if (desktopUser(doc, flags)) {
    fn();
    return () => {};
  }
  const obs = new MutationObserver(() => {
    if (!desktopUser(doc, flags)) return;
    obs.disconnect();
    fn();
  });
  obs.observe(doc.documentElement, { attributes: true, attributeFilter: ['class'] });
  obs.observe(doc.body, { attributes: true, attributeFilter: ['class'] });
  return () => obs.disconnect();
}

/**
 * Mission Control (about 190 kB with network and the chassis view) warms up after the first 10 s
 * after signing in, not inside them: at 3 s plus idle time it landed in that window on some runs
 * and not others (400 to 422 kB, budget 420; NPERF-5). Opened sooner, it loads on demand.
 */
export const MISSION_CONTROL_WARMUP_MS = 12000;

/** Runs fn once the page has settled: after `after` ms, when the browser is idle. */
export function idleLoad(fn, after = 3000, win = window) {
  const run = () => fn();
  if (typeof win.requestIdleCallback === 'function') {
    win.setTimeout(() => win.requestIdleCallback(run, { timeout: 5000 }), after);
  } else {
    win.setTimeout(run, after + 1000);
  }
}
