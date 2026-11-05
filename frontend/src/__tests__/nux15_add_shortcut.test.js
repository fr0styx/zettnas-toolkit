/** NUX-15: the Add-a-shortcut dialog and a custom shortcut's emoji use classes. */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  createShortcutElement,
  openAddDesktopShortcutModal,
  closeAddDesktopShortcutModal,
  _resetShortcutsForTesting,
} from '../components/desktop-shortcuts.js';

describe('Add a desktop shortcut (NUX-15)', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = '<div id="desktop-icons-container"></div>';
    _resetShortcutsForTesting();
  });

  it('a shortcut without an icon gets the link emoji', () => {
    expect(createShortcutElement({ id: 'sc-x', name: 'X', url: 'http://x.local' }).querySelector('.dss-emoji').textContent).toBe('🔗');
  });

  it("a custom shortcut's emoji is drawn with a class", () => {
    const el = createShortcutElement({ id: 'sc-plex', name: 'Plex', icon: '🎬', url: 'http://plex.local:32400' });
    const emoji = el.querySelector('.dss-emoji');
    expect(emoji.textContent).toBe('🎬');
    expect(emoji.hasAttribute('style')).toBe(false);
  });

  it('the built-in shortcuts are cards with their badge, and only the panes keep a display', () => {
    openAddDesktopShortcutModal();
    const overlay = document.getElementById('add-desktop-shortcut-overlay');
    expect(overlay.querySelectorAll('.asd-card').length).toBeGreaterThan(3);
    expect(overlay.querySelector('#pane-system-shortcuts').getAttribute('style')).toBe('display:flex;');
    expect(overlay.querySelector('#pane-custom-shortcut').getAttribute('style')).toBe('display:none;');
    closeAddDesktopShortcutModal();
  });
});
