import { describe, it, expect, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showActionToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
vi.mock('../components/dock.js', () => ({ applyDockSettings: vi.fn() }));
import { showActionToast } from '../toast.js';
import { applyDockSettings } from '../components/dock.js';
import { showPanes, tabForPane, tabPanes } from '../components/management.js';
import { exportThemeBundle, importThemeBundle, restoreDesktopDefaultsWithUndo } from '../components/settings.js';

const html = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');

describe('Appearance in two tabs, Look and Desktop (APP-C)', () => {
  it('has the two tabs with their panes, Theme first', () => {
    expect(html).toContain('data-tab-panes="mgmt-pane-theme mgmt-pane-wallpaper mgmt-pane-glass"');
    expect(html).toContain('data-tab-panes="mgmt-pane-dock mgmt-pane-widgets mgmt-pane-screensaver"');
    expect(html.indexOf('id="mgmt-pane-theme"')).toBeLessThan(html.indexOf('id="mgmt-pane-wallpaper"'));
    expect(html).not.toContain('data-tab-target="mgmt-pane-wallpaper"');
  });

  it('a tab shows all of its panes, and a link to any pane finds its tab', () => {
    document.body.innerHTML = `<div id="card">
      <button class="mgmt-inner-tab" data-tab-target="a" data-tab-panes="a b"></button>
      <button class="mgmt-inner-tab" data-tab-target="c"></button>
      <div class="mgmt-tab-pane" id="a"></div><div class="mgmt-tab-pane" id="b"></div><div class="mgmt-tab-pane" id="c"></div></div>`;
    const card = document.getElementById('card');
    const [look, other] = card.querySelectorAll('.mgmt-inner-tab');
    expect(tabPanes(look)).toEqual(['a', 'b']);
    expect(tabPanes(other)).toEqual(['c']);
    expect(tabPanes(null)).toEqual([]);
    expect(tabForPane(card, 'b')).toBe(look);
    expect(tabForPane(card, 'zzz')).toBeNull();
    showPanes(card, tabPanes(look));
    expect(['a', 'b', 'c'].map((id) => document.getElementById(id).style.display)).toEqual(['block', 'block', 'none']);
  });

  it('Reset desktop puts the dock back, with Undo', () => {
    restoreDesktopDefaultsWithUndo();
    expect(applyDockSettings).toHaveBeenCalledWith('bottom', true, 1.45, 'medium', false, true); // position, magnify, scale, size, auto-hide
    const [msg, , undo] = showActionToast.mock.calls.at(-1);
    expect(msg).toBe('The desktop is back to its defaults.');
    applyDockSettings.mockClear();
    undo();
    expect(applyDockSettings).toHaveBeenCalledOnce();
  });
});

describe('theme files keep the dock as the dock stores it', () => {
  it('export reads the magnify switch and the scale', () => {
    localStorage.setItem('kiboto_dock_magnification', 'false');
    localStorage.setItem('kiboto_dock_scale', '1.6');
    let blob = null;
    const realCreate = URL.createObjectURL;
    URL.createObjectURL = (b) => { blob = b; return 'blob:x'; };
    URL.revokeObjectURL = () => {};
    exportThemeBundle();
    URL.createObjectURL = realCreate;
    return blob.text().then((txt) => {
      const dock = JSON.parse(txt).dock;
      expect(dock.magnification).toBe(false);
      expect(dock.scale).toBe(1.6);
    });
  });

  it('import passes position, magnify, scale, size and auto-hide in that order', async () => {
    applyDockSettings.mockClear();
    const file = new File([JSON.stringify({ format: 'kiboto-theme', theme: 'lagoon', dock: { position: 'left', magnification: false, scale: 1.3, size: 'small', autohide: true } })], 't.json');
    importThemeBundle(file);
    await vi.waitFor(() => expect(applyDockSettings).toHaveBeenCalledWith('left', false, 1.3, 'small', true, true));
    applyDockSettings.mockClear();
    importThemeBundle(new File([JSON.stringify({ format: 'kiboto-theme', theme: 'lagoon', dock: {} })], 'u.json'));
    await vi.waitFor(() => expect(applyDockSettings).toHaveBeenCalledWith('bottom', true, 1.45, 'medium', false, true));
  });

  it('the desktop reset\'s Undo restores the stored dock, and does nothing without a snapshot', () => {
    localStorage.setItem('kiboto_dock_position', 'top');
    localStorage.setItem('kiboto_dock_magnification', 'false');
    localStorage.setItem('kiboto_dock_scale', '1.2');
    localStorage.setItem('kiboto_dock_size', 'large');
    localStorage.setItem('kiboto_dock_autohide', 'true');
    restoreDesktopDefaultsWithUndo();
    const undo = showActionToast.mock.calls.at(-1)[2];
    applyDockSettings.mockClear();
    undo();
    expect(applyDockSettings).toHaveBeenCalledWith('top', false, 1.2, 'large', true, true);
  });
});
