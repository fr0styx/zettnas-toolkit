import { describe, it, expect, vi, afterEach } from 'vitest';
import { enablePhoneShell, onPhoneBack } from '../components/phone-shell.js';

const tick = () => new Promise((r) => setTimeout(r, 40));

function openPage(id) {
  const w = document.createElement('div');
  w.className = 'os-window';
  w.id = id;
  w.style.zIndex = '1000';
  w.innerHTML = '<button class="close-btn"></button>';
  w.querySelector('.close-btn').onclick = () => { w.style.display = 'none'; };
  document.body.appendChild(w);
  return w;
}

describe("the phone's own Back (UX-15)", () => {
  afterEach(() => enablePhoneShell(false));

  it('adds one history entry while a page is open, and Back closes the page', async () => {
    document.body.innerHTML = '';
    enablePhoneShell(true);
    const push = vi.spyOn(history, 'pushState');
    const page = openPage('files');
    await tick();
    expect(push).toHaveBeenCalledTimes(1);
    expect(history.state).toEqual({ zettPhonePage: true });
    onPhoneBack(); // the browser went back
    await tick();
    expect(page.style.display).toBe('none');
    push.mockRestore();
  });

  it('closes an open dialog before the page under it', async () => {
    document.body.innerHTML = '';
    enablePhoneShell(true);
    const page = openPage('vms');
    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    document.body.appendChild(dialog);
    const esc = vi.fn();
    document.addEventListener('keydown', esc);
    await tick();
    onPhoneBack();
    expect(esc).toHaveBeenCalledWith(expect.objectContaining({ key: 'Escape' }));
    expect(page.style.display).not.toBe('none');
    document.removeEventListener('keydown', esc);
  });

  it('takes its entry back when the page is closed on screen', async () => {
    document.body.innerHTML = '';
    enablePhoneShell(true);
    const page = openPage('apps');
    await tick();
    const back = vi.spyOn(history, 'back').mockImplementation(() => {});
    page.querySelector('.close-btn').click();
    await tick();
    expect(back).toHaveBeenCalledTimes(1);
    onPhoneBack(); // the popstate from that history.back() is ignored
    back.mockRestore();
  });
});
