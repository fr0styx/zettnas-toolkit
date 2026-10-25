/**
 * Hidden tabs stop listening (PERF-3, PERF-11).
 *
 * A tab left in the background kept the live stats stream open: the phone radio stayed awake
 * for an update every two seconds, and the server counted it as someone looking, so container
 * stats ran at full speed. After 30 seconds hidden the stream closes; showing the tab again
 * reconnects, and the first message is a full snapshot.
 */
export const HIDDEN_PAUSE_MS = 30000;

export function installHiddenPause({ start, stop, enabled = () => true, delayMs = HIDDEN_PAUSE_MS, doc = document }) {
  let timer = null;
  let paused = false;
  const onChange = () => {
    if (!enabled()) return;
    if (doc.hidden) {
      clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        paused = true;
        stop();
      }, delayMs);
    } else {
      clearTimeout(timer);
      timer = null;
      if (paused) {
        paused = false;
        start();
      }
    }
  };
  doc.addEventListener('visibilitychange', onChange);
  return {
    isPaused: () => paused,
    dispose: () => doc.removeEventListener('visibilitychange', onChange),
  };
}

/** True when nobody can see this page, so timers that only update the screen can skip a beat. */
export function pageHidden(doc = typeof document !== 'undefined' ? document : null) {
  return Boolean(doc && doc.hidden);
}
