/**
 * ZettNAS Toolkit - Touch Haptics Engine
 * Provides subtle tactile feedback on mobile devices using navigator.vibrate()
 */

export function triggerHaptic(type = 'light') {
  if (typeof navigator === 'undefined' || typeof navigator.vibrate !== 'function') {
    return false;
  }
  try {
    if (type === 'light') {
      navigator.vibrate(12);
    } else if (type === 'medium') {
      navigator.vibrate(25);
    } else if (type === 'heavy') {
      navigator.vibrate(45);
    } else if (type === 'success') {
      navigator.vibrate([15, 30, 20]);
    } else if (type === 'warning' || type === 'error') {
      navigator.vibrate([30, 50, 30]);
    }
    return true;
  } catch (err) {
    return false;
  }
}
