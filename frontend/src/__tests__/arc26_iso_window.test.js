/** ARC-26: the ISO library window: its controls, drag and drop, and the upload's progress. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { openIsoManagerModal } from '../components/vm-manager.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';

vi.mock('../api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  auth: { hasToken: vi.fn().mockReturnValue(true), getToken: vi.fn(() => 'x') },
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

const q = (sel) => document.querySelector(sel);
let xhrs = [];
class FakeXhr {
  constructor() {
    this.upload = {};
    this.headers = {};
    xhrs.push(this);
  }
  open(method, url) { Object.assign(this, { method, url }); }
  setRequestHeader(k, v) { this.headers[k] = v; }
  send(body) { this.body = body; }
}
const iso = (name = 'debian.iso') => new File(['x'], name);

describe('ISO library window', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
    xhrs = [];
    vi.stubGlobal('XMLHttpRequest', FakeXhr);
    api.get.mockImplementation(async (url) => (url === '/api/vms/isos' || url === '/api/vms/bridges' ? [] : url === '/api/vms' ? [] : {}));
    window.DockManager = { windows: {}, register: vi.fn(), minimize: vi.fn(), closeWindow: vi.fn(), restore: vi.fn() };
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    delete window.DockManager;
    document.getElementById('modal-iso-manager')?.remove();
  });

  it('maximises, restores, minimises and closes', async () => {
    await openIsoManagerModal('local');
    const win = q('#modal-iso-manager');
    const left = win.style.left;
    q('#iso-win-max').click();
    expect(win.style.width).toBe('100vw');
    q('#iso-win-max').click();
    expect(win.style.left).toBe(left);
    q('#iso-win-min').click();
    expect(window.DockManager.minimize).toHaveBeenCalledWith('vm-iso-manager');
    expect(win.classList.contains('window-minimized')).toBe(true);
    await openIsoManagerModal('catalog');
    q('#iso-modal-close').click();
    expect(window.DockManager.closeWindow).toHaveBeenCalledWith('vm-iso-manager');
  });

  it('uploads a dropped ISO with progress, and refreshes the list', async () => {
    await openIsoManagerModal('local');
    const zone = q('#iso-dropzone');
    zone.ondragover({ preventDefault() {} });
    expect(zone.style.borderColor).toBe('rgb(79, 216, 196)');
    zone.ondragleave();
    zone.ondrop({ preventDefault() {}, dataTransfer: { files: [iso()] } });
    const xhr = xhrs.at(-1);
    expect(xhr.url).toBe('/api/vms/isos/upload');
    expect(xhr.headers['x-filename']).toBe('debian.iso');
    expect(q('#upload-filename').textContent).toBe('debian.iso');

    const now = vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 1000);
    xhr.upload.onprogress({ lengthComputable: true, loaded: 5 * 1024 * 1024, total: 10 * 1024 * 1024 });
    expect(q('#upload-progress-bar').style.width).toBe('50%');
    expect(q('#upload-rate').textContent).toMatch(/MB\/s \(50%\)/);
    now.mockRestore();
    xhr.upload.onprogress({ lengthComputable: false });

    xhr.status = 200;
    await xhr.onload();
    expect(q('#upload-progress-bar').style.width).toBe('100%');
    expect(showToast.mock.calls.at(-1)[1]).toBe('success');
  });

  it('says why an upload failed', async () => {
    await openIsoManagerModal('local');
    q('#iso-dropzone').ondrop({ preventDefault() {}, dataTransfer: { files: [iso('bad.iso')] } });
    const xhr = xhrs.at(-1);
    xhr.status = 413;
    xhr.responseText = JSON.stringify({ detail: 'Too large' });
    await xhr.onload();
    expect(showToast.mock.calls.at(-1)).toEqual(['Upload failed: Too large', 'error']);
    expect(q('#upload-rate').textContent).toBe('Error: Too large');
    xhr.responseText = 'not json';
    await xhr.onload();
    expect(q('#upload-rate').textContent).toBe('Error: Upload failed');
    xhr.onerror();
    expect(showToast.mock.calls.at(-1)[1]).toBe('error');
    q('#upload-rate').remove(); // without its rate label the toast still says why
    q('#iso-dropzone').ondrop({ preventDefault() {}, dataTransfer: { files: [iso('again.iso')] } });
    const second = xhrs.at(-1);
    second.status = 500;
    second.responseText = '';
    await second.onload();
    expect(showToast.mock.calls.at(-1)).toEqual(['Upload failed: Upload failed', 'error']);
    q('#iso-dropzone').ondrop({ preventDefault() {}, dataTransfer: { files: [] } });
    expect(xhrs).toHaveLength(2);
  });

  it('the browse button opens the file picker, and a picked file uploads', async () => {
    await openIsoManagerModal('local');
    const input = q('#iso-file-input');
    const picked = vi.spyOn(input, 'click').mockImplementation(() => {});
    q('#btn-browse-iso').click();
    expect(picked).toHaveBeenCalled();
    input.onchange({ target: { files: [iso('win.iso')] } });
    expect(xhrs.at(-1).headers['x-filename']).toBe('win.iso');
    input.onchange({ target: { files: [] } });
    expect(xhrs).toHaveLength(1);
    q('#btn-refresh-local-isos').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('ISO list refreshed.', 'info'));
  });
});
