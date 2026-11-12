import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { haStatus, haCardHtml, haFormValues, loadHomeAssistantCard } = await import('../components/management/home-assistant.js');

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const CFG = { enabled: true, host: 'mqtt.lan', port: 1883, username: 'kib', has_password: true, tls: false, status: { last_ok: true, sensors: 9, last_at: 1762700000 } };

describe('Home Assistant card (RES-5)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="network-services-grid"></div>';
  });

  it('says how the last send went', () => {
    expect(haStatus({ enabled: false })).toContain('Off');
    expect(haStatus(CFG)).toContain('9 sensors sent');
    expect(haStatus({ enabled: true, status: { last_ok: false, last_error: 'refused' } })).toContain('refused');
    expect(haStatus({ enabled: true, status: {} })).toContain('first send');
  });

  it('keeps a saved password unless a new one is typed', () => {
    document.body.innerHTML = `<div>${haCardHtml(CFG)}</div>`;
    const form = /** @type {HTMLFormElement} */ (document.querySelector('[data-ha-form]'));
    expect(haFormValues(form)).toEqual({ host: 'mqtt.lan', port: 1883, username: 'kib', tls: false });
    /** @type {HTMLInputElement} */ (form.elements.namedItem('password')).value = 'new';
    expect(haFormValues(form).password).toBe('new');
  });

  it('turns on, saves, sends a test, and hides itself for others', async () => {
    api.get.mockResolvedValue({ ...CFG, enabled: false });
    await loadHomeAssistantCard();
    const card = document.getElementById('ha-card');
    api.put.mockResolvedValue(CFG);
    card.querySelector('[data-ha-toggle]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    expect(api.put).toHaveBeenCalledWith('/api/integrations/home-assistant', { enabled: true });
    api.post.mockResolvedValue({ ok: true, sensors: 9 });
    card.querySelector('[data-ha-test]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    await tick();
    expect(api.post).toHaveBeenCalledWith('/api/integrations/home-assistant/test', {});
    expect(toast.showToast).toHaveBeenCalledWith('9 sensors sent to Home Assistant.', 'success');
    card.querySelector('[data-ha-form]').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await tick();
    expect(api.put).toHaveBeenLastCalledWith('/api/integrations/home-assistant', { host: 'mqtt.lan', port: 1883, username: 'kib', tls: false });
    api.post.mockRejectedValueOnce(new Error('The broker did not take it'));
    card.querySelector('[data-ha-test]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    await tick();
    expect(toast.showToast).toHaveBeenCalledWith('The broker did not take it', 'error');
    api.get.mockRejectedValue(new Error('forbidden'));
    await loadHomeAssistantCard();
    expect(document.getElementById('ha-card').hidden).toBe(true);
  });

  it('builds into its new place when that is there (SET-24)', async () => {
    document.body.innerHTML = '<div id="notif-ha-grid"></div><div id="network-services-grid"></div>';
    await loadHomeAssistantCard();
    expect(document.getElementById('ha-card').parentElement.id).toBe('notif-ha-grid');
  });
});
