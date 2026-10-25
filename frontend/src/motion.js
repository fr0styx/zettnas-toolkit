/**
 * Reduced motion in JavaScript (UX-19): the CSS already honours prefers-reduced-motion; moving
 * canvases and pointer effects ask here before they animate.
 */
const QUERY = '(prefers-reduced-motion: reduce)';

export function prefersReducedMotion() {
  try {
    return Boolean(typeof window !== 'undefined' && window.matchMedia && window.matchMedia(QUERY).matches);
  } catch {
    return false;
  }
}

/** Calls cb(reduced) whenever the setting changes; returns a function that stops listening. */
export function onReducedMotionChange(cb) {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {};
  const mq = window.matchMedia(QUERY);
  const handler = (e) => cb(Boolean(e.matches));
  mq.addEventListener?.('change', handler);
  return () => mq.removeEventListener?.('change', handler);
}
