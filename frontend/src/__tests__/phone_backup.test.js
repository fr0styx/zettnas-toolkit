import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
vi.mock('qrcode', () => ({ default: { toString: vi.fn(async (text) => `<svg data-qr="${text}"></svg>`) } }));
const { api } = await import('../api.js');
const { installPhoneBackup, phoneBackupHtml } = await import('../components/phone-backup.js');

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('Back up my phone', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="immich-settings-mount"></div>';
    vi.clearAllMocks();
  });

  it('shows the address as a QR code with the steps', async () => {
    api.get.mockResolvedValue({ url: 'http://nas.local:2283', sso: true, phone_done: false });
    await installPhoneBackup(document.getElementById('immich-settings-mount'));
    const card = document.getElementById('phone-backup-card');
    expect(card.querySelector('svg').dataset.qr).toBe('http://nas.local:2283');
    expect(card.textContent).toContain('Sign in with ZettNAS');
    expect(card.textContent).toContain('http://nas.local:2283');
  });

  it('remembers that the phone backs up', async () => {
    api.get.mockResolvedValueOnce({ url: 'http://nas.local:2283', phone_done: false });
    api.get.mockResolvedValueOnce({ url: 'http://nas.local:2283', phone_done: true });
    api.put.mockResolvedValue({ done: true });
    await installPhoneBackup(document.getElementById('immich-settings-mount'));
    document.querySelector('[data-phone-done]').click();
    await flush();
    await flush();
    expect(api.put).toHaveBeenCalledWith('/api/immich/phone', { done: true });
    expect(document.getElementById('phone-backup-card').textContent).toContain('You said your phone backs up here');
  });

  it('points to the app catalog when there is no Immich', async () => {
    window.openManagementSection = vi.fn();
    api.get.mockResolvedValue({ url: '', detected: '' });
    await installPhoneBackup(document.getElementById('immich-settings-mount'));
    document.querySelector('[data-phone-open]').click();
    expect(window.openManagementSection).toHaveBeenCalledWith('catalog');
    expect(String(phoneBackupHtml({ url: 'x', sso: false }))).toContain('Sign in with your Immich account');
  });

  it('uses a detected address and escapes it', () => {
    expect(String(phoneBackupHtml({ detected: 'http://<b>' }))).not.toContain('<b>');
  });
});
