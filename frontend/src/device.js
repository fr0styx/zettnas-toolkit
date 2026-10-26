// One definition of each kind of screen (UX-15). Code asks these; CSS uses the same numbers.
//
// compact: windows fill the screen and are not dragged (a narrow window, the phone shell, or
//   the "mobile mode" someone chose in the dock). CSS: @media (max-width: 768px).
// phone: the phone shell with its launcher and tabs. CSS: body.phone-shell.
// touch: the main pointer is a finger, at any width; controls get touch-sized targets
//   (styles/61-touch.css). A portrait tablet is not compact, but it is touch.

export const COMPACT_MAX = 768;
export const PHONE_QUERY = '(max-width: 600px)';
export const TOUCH_QUERY = '(pointer: coarse)';

const body = () => (typeof document !== 'undefined' ? document.body : null);
const matches = (query) => typeof window !== 'undefined' && Boolean(window.matchMedia?.(query).matches);

export function isCompact() {
  const b = body();
  if (b && (b.classList.contains('mobile-mode') || b.classList.contains('phone-shell'))) return true;
  return typeof window !== 'undefined' && window.innerWidth <= COMPACT_MAX;
}

export function isPhone() {
  return matches(PHONE_QUERY);
}

export function isTouch() {
  return matches(TOUCH_QUERY);
}
