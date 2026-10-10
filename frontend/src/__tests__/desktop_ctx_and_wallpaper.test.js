import { describe, it, expect, beforeEach, vi } from 'vitest';
import { initDraggableDesktopIcons, showDockItemContextMenu, DockManager } from '../components/dock.js';
import { setWallpaper, loadWallpapers, renameWallpaper, deleteWallpaper } from '../components/wallpapers.js';
import { api } from '../api.js';

describe('Desktop Context Menu, Dock Context Menu, and Wallpaper Engine', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="os-dock-container">
        <div id="os-dock"></div>
      </div>
      <div class="chassis-workbench-stage" style="width:1000px; height:800px;">
        <div id="management-desktop-icon" class="chassis-hero-box" style="position:absolute; left:24px; top:77px; width:100px; height:80px;">
          <div class="icon-text">Mission Control</div>
        </div>
        <div id="fm-desktop-icon" class="chassis-hero-box" style="position:absolute; left:24px; top:189px; width:100px; height:80px;">
          <div class="icon-text">File Explorer</div>
        </div>
        <div id="rb-desktop-icon" class="chassis-hero-box" style="position:absolute; left:24px; top:301px; width:100px; height:80px;">
          <div class="icon-text">Recycle Bin</div>
        </div>
        <div id="chassis-desktop-icon" class="chassis-hero-box" style="position:absolute; left:24px; top:413px; width:100px; height:80px;">
          <div class="icon-text">ZettNAS</div>
        </div>
      </div>
      <select id="wallpaper-select"></select>
    `;
  });

  it('initDraggableDesktopIcons creates #desktop-ctx-menu attached to document.body', () => {
    initDraggableDesktopIcons();
    const menu = document.getElementById('desktop-ctx-menu');
    expect(menu).not.toBeNull();
    expect(menu.parentNode).toBe(document.body);
    expect(menu.classList.contains('desktop-context-menu')).toBe(true);
  });

  it('right-clicking desktop stage displays desktop context menu with only align and sort options', () => {
    initDraggableDesktopIcons();
    const menu = document.getElementById('desktop-ctx-menu');
    expect(menu.style.display).toBe('none');

    const stage = document.querySelector('.chassis-workbench-stage');
    const evt = new MouseEvent('contextmenu', {
      bubbles: true,
      cancelable: true,
      clientX: 350,
      clientY: 250
    });
    stage.dispatchEvent(evt);

    expect(menu.style.display).toBe('block');
    expect(menu.querySelector('#ctx-align-grid')).not.toBeNull();
    expect(menu.querySelector('#ctx-sort-name')).not.toBeNull();
    // Verify Pin Apps is removed from desktop right-click
    expect(menu.querySelector('[data-pin-id]')).toBeNull();
    expect(menu.textContent).not.toContain('PIN APPS TO DOCK');
  });

  it('right-clicking a desktop icon displays app-specific context menu with Open and organization actions', () => {
    initDraggableDesktopIcons();
    const menu = document.getElementById('desktop-ctx-menu');
    const icon = document.getElementById('management-desktop-icon');

    const evt = new MouseEvent('contextmenu', {
      bubbles: true,
      cancelable: true,
      clientX: 30,
      clientY: 60
    });
    icon.dispatchEvent(evt);

    expect(menu.style.display).toBe('block');
    expect(menu.querySelector('#ctx-open-app')).not.toBeNull();
    expect(menu.querySelector('#ctx-align-grid')).not.toBeNull();
    expect(menu.querySelector('#ctx-sort-name')).not.toBeNull();
    expect(menu.textContent).not.toContain('PIN APPS TO DOCK');
  });

  it('showDockItemContextMenu shows Pin to Dock for an unpinned open app', () => {
    showDockItemContextMenu(200, 700, 'fm', 'File Explorer', false, true);
    const menu = document.getElementById('dock-item-ctx-menu');
    expect(menu).not.toBeNull();
    expect(menu.parentNode).toBe(document.body);
    expect(menu.style.display).toBe('block');
    expect(menu.querySelector('#dock-ctx-pin')).not.toBeNull();
    expect(menu.querySelector('#dock-ctx-pin').textContent).toContain('Pin to Dock');
    expect(menu.querySelector('#dock-ctx-close')).not.toBeNull();
    expect(menu.textContent).not.toContain('PIN APPS TO DOCK');
  });

  it('showDockItemContextMenu shows Unpin from Dock for an already pinned app', () => {
    showDockItemContextMenu(200, 700, 'fm', 'File Explorer', true, true);
    const menu = document.getElementById('dock-item-ctx-menu');
    expect(menu).not.toBeNull();
    expect(menu.style.display).toBe('block');
    expect(menu.querySelector('#dock-ctx-pin')).not.toBeNull();
    expect(menu.querySelector('#dock-ctx-pin').textContent).toContain('Unpin from Dock');
    expect(menu.querySelector('#dock-ctx-close')).not.toBeNull();
    expect(menu.textContent).not.toContain('PIN APPS TO DOCK');
  });

  it('showDockItemContextMenu does not display menu for home or notif', () => {
    showDockItemContextMenu(200, 700, 'home', 'Dashboard Home', false, false);
    const menu = document.getElementById('dock-item-ctx-menu');
    expect(menu).toBeNull();
  });

  it('setWallpaper applies background-image property with important flag', () => {
    setWallpaper('/api/wallpapers/download/bahia.jpg');
    expect(document.body.style.getPropertyValue('background-image')).toContain('bahia.jpg');
    expect(document.body.style.getPropertyPriority('background-image')).toBe('important');

    setWallpaper(null);
    expect(document.body.style.getPropertyValue('background-image')).toBe('');
  });

  it('loadWallpapers retrieves active wallpaper and invokes setWallpaper', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({
      files: ['bahia.jpg', 'sunset.png'],
      active: 'bahia.jpg'
    });

    await loadWallpapers();
    expect(document.body.style.getPropertyValue('background-image')).toContain('bahia.jpg');
    const select = document.getElementById('wallpaper-select');
    expect(select.value).toBe('bahia.jpg');
    expect(select.options.length).toBe(3); // Default + 2 files
  });

  it('positions Mission Control at top: 77px with equal 25px gap from navbar, and keeps it at top on Sort by Name', () => {
    initDraggableDesktopIcons();
    const mc = document.getElementById('management-desktop-icon');
    const fm = document.getElementById('fm-desktop-icon');
    expect(mc.style.top).toBe('77px');
    expect(fm.style.top).toBe('189px');

    // Trigger desktop context menu
    const stage = document.querySelector('.chassis-workbench-stage');
    stage.dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true,
      cancelable: true,
      clientX: 350,
      clientY: 250
    }));

    const sortBtn = document.getElementById('ctx-sort-name');
    expect(sortBtn).not.toBeNull();
    sortBtn.click();

    // Mission Control must remain anchored at top (77px)
    expect(mc.style.top).toBe('77px');
    expect(fm.style.top).toBe('189px');
  });

  it('renameWallpaper uses custom OS prompt modal instead of browser prompt', async () => {
    const promptSpy = vi.spyOn(window, 'prompt');
    const apiSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ success: true, new_name: 'bahia_new.jpg' });

    renameWallpaper('bahia.jpg');

    // Must NOT call browser prompt
    expect(promptSpy).not.toHaveBeenCalled();

    // Verify custom OS modal rendered
    const modal = document.getElementById('confirm-toast-modal');
    expect(modal).not.toBeNull();
    const input = document.getElementById('prompt-toast-input');
    expect(input).not.toBeNull();
    expect(input.value).toBe('bahia.jpg');

    // Change value and submit via confirm button
    input.value = 'bahia_new.jpg';
    const confirmBtn = document.getElementById('confirm-toast-ok');
    confirmBtn.click();

    await Promise.resolve();
    expect(apiSpy).toHaveBeenCalledWith('/api/wallpapers/rename', {
      old_name: 'bahia.jpg',
      new_name: 'bahia_new.jpg'
    });
  });

  it('deleteWallpaper uses custom OS confirm modal instead of browser confirm', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    const apiSpy = vi.spyOn(api, 'delete').mockResolvedValueOnce({ success: true });

    deleteWallpaper('bahia.jpg');

    // Must NOT call browser confirm
    expect(confirmSpy).not.toHaveBeenCalled();

    // Verify custom OS modal rendered
    const modal = document.getElementById('confirm-toast-modal');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain('bahia.jpg');

    // Confirm deletion
    const okBtn = document.getElementById('confirm-toast-ok');
    okBtn.click();

    await Promise.resolve();
    expect(apiSpy).toHaveBeenCalledWith('/api/wallpapers/bahia.jpg');
  });
});
