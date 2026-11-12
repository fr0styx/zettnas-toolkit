/**
 * One poll helper for windows that wait on something (SET-16 stage 2).
 *
 * A pane that waits for a sign-in or an approval asks the server again every few seconds. It stops
 * when the answer comes (`check` returns true), after `limit` tries, after an error, or as soon as
 * its element is gone or hidden: a closed window asks nothing more. Opening the pane again starts
 * a new poll.
 */

/** True while the element is in the page and can be seen. */
export function isOpen(el) {
  if (!el || !el.isConnected) return false;
  if (typeof el.checkVisibility === 'function') return el.checkVisibility();
  for (let n = el; n; n = n.parentElement) {
    if (n.hidden) return false;
  }
  return true;
}

/**
 * Calls `check` every `ms` while `el` is open. Returns a function that stops it.
 * @param {Element} el
 * @param {() => Promise<boolean|void>|boolean|void} check
 * @param {{ms: number, limit: number}} opts
 */
export function pollWhileOpen(el, check, { ms, limit }) {
  let timer = null;
  let tries = 0;
  let stopped = false;
  const stop = () => {
    stopped = true;
    clearTimeout(timer);
  };
  const tick = async () => {
    if (stopped || !isOpen(el)) return stop();
    tries += 1;
    let done;
    try {
      done = Boolean(await check());
    } catch {
      done = true; // keep what is shown; the next open of the pane asks again
    }
    if (done || tries >= limit) return stop();
    if (!stopped) timer = setTimeout(tick, ms);
  };
  timer = setTimeout(tick, ms);
  return stop;
}
