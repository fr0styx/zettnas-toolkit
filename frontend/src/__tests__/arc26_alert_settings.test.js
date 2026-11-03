/** The alert settings pane: what it shows from the saved settings, what it saves back, and the test buttons. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
vi.mock('../components/my-alerts.js', () => ({ renderMyAlerts: vi.fn() }));
vi.mock('../components/frigate-events.js', () => ({ renderFrigateEvents: vi.fn() }));

const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { setLanguage } = await import('../i18n.js');
const { renderFrigateEvents } = await import('../components/frigate-events.js');
const n = await import('../components/management/notifications.js');

const $ = (id) => document.getElementById(id);
const PANE = `
  <select id="notif-digest-mode"><option value="off">off</option><option value="daily">daily</option></select>
  <input id="notif-digest-hour"><input type="checkbox" id="notif-weekly-report"><select id="notif-language"></select>
  <div id="my-alerts-mount"></div><div id="frigate-events-mount"></div>
  <input type="checkbox" id="notif-master-enabled"><span id="notif-master-status-badge"></span>
  ${['discord', 'telegram', 'email', 'ntfy', 'webhook', 'apprise'].map((c) => `<span id="notif-badge-${c}"></span>`).join('')}
  ${['smart', 'ups', 'temp', 'fan', 'copy', 'container', 'backup'].map((c) => `<input type="checkbox" id="notif-toggle-${c}">`).join('')}
  <input id="notif-input-hdd-temp"><input id="notif-input-cpu-temp"><input id="notif-input-cooldown">
  <button id="btn-send-test-alert"></button><button class="notif-test-btn" data-channel="ntfy">Test</button>
  <div id="modal-notification-channel"><h3 id="notif-modal-title"></h3><div id="notif-modal-body"></div>
    <input type="checkbox" id="notif-modal-channel-enable"></div>`;

async function load(cfg) {
  vi.spyOn(api, 'get').mockResolvedValue(cfg);
  await n.fetchAndRenderNotificationConfig();
}
let post;
beforeEach(() => {
  document.body.innerHTML = PANE;
  post = vi.spyOn(api, 'post').mockImplementation(async (_url, body) => ({ config: { ...body } }));
});
afterEach(async () => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  await setLanguage('en');
});

describe('alert settings pane', () => {
  it('shows a fully set-up household', async () => {
    await load({
      enabled: true, digest_mode: 'daily', digest_hour: 19, weekly_report: false, language: 'de',
      discord_enabled: true, discord_webhook_url: 'https://d', telegram_enabled: true, telegram_bot_token: 'x', telegram_chat_id: '1',
      email_enabled: true, smtp_host: 'mail', ntfy_enabled: true, ntfy_topic: 'nas', webhook_enabled: true, webhook_url: 'https://w',
      apprise_urls: ['a://1', 'b://2'], notify_on_fan: false, hdd_temp_threshold: 45, cpu_temp_threshold: 90, cooldown_seconds: 600,
    });
    expect($('notif-digest-mode').value).toBe('daily');
    expect($('notif-digest-hour').value).toBe('19');
    expect($('notif-weekly-report').checked).toBe(false);
    expect($('notif-language').value).toBe('de');
    expect($('notif-language').options.length).toBeGreaterThan(1);
    expect($('notif-master-status-badge').textContent).toBe('Active');
    for (const c of ['discord', 'telegram', 'email', 'ntfy', 'webhook']) expect($(`notif-badge-${c}`).textContent).toBe('Active');
    expect($('notif-badge-apprise').textContent).toBe('2 URLs');
    expect($('notif-toggle-fan').checked).toBe(false);
    expect($('notif-toggle-smart').checked).toBe(true);
    expect([$('notif-input-hdd-temp').value, $('notif-input-cpu-temp').value, $('notif-input-cooldown').value]).toEqual(['45', '90', '10']);
    await vi.waitFor(() => expect(renderFrigateEvents).toHaveBeenCalledWith($('frigate-events-mount')));
  });

  it('shows defaults for an empty household, in German', async () => {
    await setLanguage('de');
    await load(null);
    expect($('notif-digest-mode').value).toBe('off');
    expect($('notif-digest-hour').value).toBe('8');
    expect($('notif-weekly-report').checked).toBe(true);
    expect($('notif-language').value).toBe('en');
    expect($('notif-master-status-badge').textContent).not.toBe('Active');
    expect($('notif-badge-apprise').textContent).toBe($('notif-badge-discord').textContent);
    expect([$('notif-input-hdd-temp').value, $('notif-input-cpu-temp').value, $('notif-input-cooldown').value]).toEqual(['50', '80', '30']);
  });

  it('says when the settings could not be read', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(api, 'get').mockRejectedValue(new Error('500'));
    await n.fetchAndRenderNotificationConfig();
    expect(showToast).toHaveBeenCalledWith('Failed to load notification settings', 'error');
  });

  it('saves the switches and keeps the numbers in range', async () => {
    await load({});
    $('notif-master-enabled').checked = true;
    $('notif-toggle-ups').checked = false;
    $('notif-input-hdd-temp').value = '99';
    $('notif-input-cpu-temp').value = '10';
    $('notif-input-cooldown').value = '0';
    $('notif-digest-mode').value = 'daily';
    $('notif-digest-hour').value = '30';
    $('notif-weekly-report').checked = false;
    $('notif-language').value = 'fr';
    await n.saveNotificationsConfig();
    const sent = post.mock.calls[0][1];
    expect(post.mock.calls[0][0]).toBe('/api/notifications/config');
    expect(sent).toMatchObject({
      enabled: true, notify_on_ups: false, notify_on_smart: true, hdd_temp_threshold: 80, cpu_temp_threshold: 40,
      cooldown_seconds: 60, digest_mode: 'daily', digest_hour: 23, weekly_report: false, language: 'fr',
    });
    expect(showToast).toHaveBeenLastCalledWith('Notification settings saved successfully!', 'success');
    expect($('notif-master-status-badge').textContent).toBe('Active');
  });

  it('leaves out numbers that are not numbers and says why a save failed', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    await load({ hdd_temp_threshold: 41 });
    $('notif-input-hdd-temp').value = 'abc';
    post.mockRejectedValueOnce(new Error('Forbidden'));
    await n.saveNotificationsConfig();
    expect(post.mock.calls[0][1].hdd_temp_threshold).toBe(41);
    expect(showToast).toHaveBeenLastCalledWith('Forbidden', 'error');
    post.mockRejectedValueOnce(new Error(''));
    await n.saveNotificationsConfig();
    expect(showToast).toHaveBeenLastCalledWith('Failed to save the notification settings', 'error');
    post.mockResolvedValueOnce({});
    await n.saveNotificationsConfig();
    expect(showToast).toHaveBeenLastCalledWith('Notification settings saved successfully!', 'success');
  });

  it('sends a test to every channel and names the ones that worked', async () => {
    const btn = $('btn-send-test-alert');
    post.mockResolvedValueOnce({ tested_channels: { discord: true, email: false, ntfy: true } });
    const run = n.testAllNotificationChannels();
    expect(btn.disabled).toBe(true);
    await run;
    expect(showToast).toHaveBeenLastCalledWith('✓ Test alerts delivered to: discord, ntfy', 'success');
    expect(btn.disabled).toBe(false);
    expect(btn.textContent).toBe('⚡ Send Test Alert');
    post.mockResolvedValueOnce({ tested_channels: { email: false } });
    await n.testAllNotificationChannels();
    expect(showToast.mock.lastCall[1]).toBe('warning');
    post.mockResolvedValueOnce(null);
    await n.testAllNotificationChannels();
    expect(showToast.mock.lastCall[1]).toBe('warning');
    post.mockRejectedValueOnce(new Error('timeout'));
    await setLanguage('es');
    await n.testAllNotificationChannels();
    expect(showToast.mock.lastCall[1]).toBe('error');
    expect(btn.textContent).toBe('⚡ Enviar alerta de prueba');
    document.body.innerHTML = '';
    post.mockResolvedValueOnce({ tested_channels: {} });
    await n.testAllNotificationChannels();
  });

  it('tests one channel with the settings on screen', async () => {
    await load({ ntfy_topic: 'nas' });
    const btn = document.querySelector('.notif-test-btn');
    post.mockResolvedValueOnce({ success: true, latency_ms: 42 });
    await n.testSingleChannel('ntfy');
    expect(post).toHaveBeenCalledWith('/api/notifications/test-channel', { channel: 'ntfy', config: expect.objectContaining({ ntfy_topic: 'nas' }) });
    expect(showToast).toHaveBeenLastCalledWith('✓ NTFY: Delivered in 42ms', 'success');
    expect(btn.textContent).toBe('Test');
    expect(btn.disabled).toBe(false);
    post.mockRejectedValueOnce(new Error('refused'));
    await n.testSingleChannel('webhook');
    expect(showToast).toHaveBeenLastCalledWith('Test failed for webhook: refused', 'error');
  });

  it('every channel dialog saves what was typed and keeps a hidden secret', async () => {
    await load({ telegram_bot_token: 'old', smtp_pass: 'oldpass', ntfy_token: 'oldtk' });
    const type = (id, v) => { $(id).value = v; };
    const save = async (channel, fill, enable = true) => {
      n.openChannelConfigModal(channel);
      expect($('modal-notification-channel').style.display).toBe('flex');
      $('notif-modal-channel-enable').checked = enable;
      fill();
      n.saveCurrentChannelModal();
      expect($('modal-notification-channel').style.display).toBe('none');
      await vi.waitFor(() => expect(post.mock.calls.length).toBeGreaterThan(0));
      return post.mock.lastCall[1];
    };
    expect(await save('discord', () => type('cfg-discord-url', ' https://d/1 '))).toMatchObject({ discord_enabled: true, discord_webhook_url: 'https://d/1' });
    expect(await save('telegram', () => { type('cfg-telegram-token', '********'); type('cfg-telegram-chat', '-100'); })).toMatchObject({ telegram_bot_token: 'old', telegram_chat_id: '-100' });
    expect(await save('telegram', () => type('cfg-telegram-token', 'new'))).toMatchObject({ telegram_bot_token: 'new' });
    const mail = await save('email', () => {
      type('cfg-smtp-host', 'smtp.x'); type('cfg-smtp-port', 'x'); type('cfg-smtp-user', 'u');
      type('cfg-smtp-pass', '********'); type('cfg-email-from', 'a@x'); type('cfg-email-to', 'b@x');
      $('cfg-smtp-tls').checked = false;
    });
    expect(mail).toMatchObject({ email_enabled: true, smtp_host: 'smtp.x', smtp_port: 587, smtp_pass: 'oldpass', smtp_tls: false, email_from: 'a@x', email_to: 'b@x' });
    expect(await save('email', () => type('cfg-smtp-pass', 'p2'))).toMatchObject({ smtp_pass: 'p2', smtp_port: 587 });
    expect(await save('ntfy', () => { type('cfg-ntfy-url', ''); type('cfg-ntfy-topic', 't'); type('cfg-ntfy-token', ''); }, false))
      .toMatchObject({ ntfy_enabled: false, ntfy_url: 'https://ntfy.sh', ntfy_topic: 't', ntfy_token: 'oldtk' });
    expect(await save('ntfy', () => type('cfg-ntfy-token', 'tk2'))).toMatchObject({ ntfy_token: 'tk2' });
    expect(await save('webhook', () => type('cfg-webhook-url', 'https://w'))).toMatchObject({ webhook_enabled: true, webhook_url: 'https://w' });
    expect(await save('apprise_raw', () => type('cfg-apprise-raw', ' a://1 \n\nb://2'))).toMatchObject({ apprise_urls: ['a://1', 'b://2'] });
    n.openChannelConfigModal('apprise_raw');
    expect($('cfg-apprise-raw').value).toBe('a://1\nb://2');
    n.openChannelConfigModal('email');
    expect($('cfg-smtp-port').value).toBe('587');
    expect($('notif-modal-body').textContent).toContain('PORT');
  });

  it('a dialog for an unknown channel shows nothing to fill in; missing dialogs are ignored', async () => {
    await load({});
    n.openChannelConfigModal('pager');
    expect($('notif-modal-body').innerHTML).toBe('');
    n.saveCurrentChannelModal();
    await vi.waitFor(() => expect(post).toHaveBeenCalled());
    document.body.innerHTML = '';
    n.openChannelConfigModal('discord');
    n.saveCurrentChannelModal();
    n.renderNotificationConfigUI();
  });
});
