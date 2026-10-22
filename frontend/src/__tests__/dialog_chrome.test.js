import { describe, it, expect, beforeEach } from 'vitest';
import { upgradeDialog, toggleDialogMaximize, minimizeDialog, installDialogChrome, _test } from '../dialog-chrome.js';
import { DockManager } from '../components/dock.js';

const tick = () => new Promise((r) => setTimeout(r, 0));

function popup({ id = 'modal-x', closeHtml = '<button id="x-close">✕</button>', alert = false, backdrop = true } = {}) {
  const win = `
    <div class="smart-modal-window" ${alert ? 'data-dialog-chrome="alert"' : ''}>
      <div class="smart-modal-header">
        <span class="smart-modal-title">Example dialog</span>
        ${closeHtml}
      </div>
      <div class="smart-modal-body">Body</div>
    </div>`;
  document.body.innerHTML = backdrop
    ? `<div id="${id}" class="smart-modal-backdrop open" style="display:flex">${win}</div><div id="os-dock"></div>`
    : `${win}<div id="os-dock"></div>`;
  return document.querySelector('.smart-modal-window');
}

describe('dialog-chrome: every pop-up gets the window title bar', () => {
  beforeEach(() => {
    for (const id of Array.from(_test.parked.keys())) _test.forget(id);
  });

  it('adds minimize and maximize and turns a text close button into the standard one', () => {
    const win = popup();
    let closed = 0;
    document.getElementById('x-close').addEventListener('click', () => { closed += 1; });
    expect(upgradeDialog(win)).toBe(true);

    const btns = Array.from(win.querySelectorAll('.os-window-controls .win-btn'));
    expect(btns.map((b) => b.className)).toEqual(['win-btn min-btn', 'win-btn max-btn', 'win-btn close-btn']);
    const close = btns[2];
    expect(close.id).toBe('x-close');
    expect(close.textContent).toBe('');
    expect(close.getAttribute('aria-label')).toBe('Close');
    close.click();
    expect(closed).toBe(1);
    expect(win.querySelector('.smart-modal-header').classList.contains('dialog-chrome-header')).toBe(true);
  });

  it('leaves buttons a pop-up already has alone and does nothing the second time', () => {
    const win = popup({
      closeHtml: '<div class="os-window-controls"><button class="win-btn min-btn" id="own-min"></button><button class="win-btn close-btn" id="own-close"></button></div>',
    });
    upgradeDialog(win);
    expect(upgradeDialog(win)).toBe(false);
    const ids = Array.from(win.querySelectorAll('.os-window-controls .win-btn')).map((b) => b.id || b.dataset.chrome);
    expect(ids).toEqual(['own-min', 'max', 'own-close']);
  });

  it('gives confirmations only the close button', () => {
    const win = popup({ alert: true, backdrop: false });
    upgradeDialog(win);
    expect(win.querySelector('.min-btn')).toBeNull();
    expect(win.querySelector('.max-btn')).toBeNull();
    expect(win.querySelector('.close-btn')).not.toBeNull();
  });

  it('adds a close button when there is none, which hides the pop-up', () => {
    installDialogChrome();
    const win = popup({ closeHtml: '' });
    upgradeDialog(win);
    const host = document.getElementById('modal-x');
    const close = win.querySelector('.close-btn');
    expect(close.dataset.chrome).toBe('close');
    close.click();
    expect(host.classList.contains('open')).toBe(false);
    expect(host.style.display).toBe('none');
  });

  it('maximizes and restores the window size', () => {
    const win = popup();
    win.style.width = '440px';
    expect(toggleDialogMaximize(win)).toBe(true);
    expect(win.style.position).toBe('fixed');
    expect(win.style.width).toBe('calc(100vw - 32px)');
    expect(toggleDialogMaximize(win)).toBe(false);
    expect(win.style.width).toBe('440px');
    expect(win.style.position).toBe('');
  });

  it('minimizes to the dock, comes back when reopened, and leaves the dock when closed', async () => {
    const win = popup({ id: 'modal-add-thing' });
    upgradeDialog(win);
    const host = document.getElementById('modal-add-thing');

    const id = minimizeDialog(win);
    expect(id).toBe('dlg-modal-add-thing');
    expect(DockManager.windows[id].minimized).toBe(true);
    expect(DockManager.windows[id].transient).toBe(true);
    expect(DockManager.windows[id].title).toBe('Example dialog');
    expect(host.classList.contains('open')).toBe(false);

    // The pop-up's own code opens it again
    host.classList.add('open');
    await tick();
    expect(DockManager.windows[id].minimized).toBe(false);

    // ...and closes it
    host.classList.remove('open');
    host.style.display = 'none';
    await tick();
    expect(DockManager.windows[id]).toBeUndefined();
    expect(host.classList.contains('window-minimized')).toBe(false);
  });

  it('closing from the dock goes through the pop-up\'s own close button', () => {
    const win = popup({ id: 'modal-dock-close' });
    let closed = 0;
    document.getElementById('x-close').addEventListener('click', () => { closed += 1; });
    upgradeDialog(win);
    const id = minimizeDialog(win);
    DockManager.closeWindow(id);
    expect(closed).toBe(1);
    expect(DockManager.windows[id]).toBeUndefined();
  });
});
