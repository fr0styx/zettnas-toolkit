/** NUX-20: the alert channel badges, test results and channel settings dialogs read as translatable words. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  fetchAndRenderNotificationConfig,
  openChannelConfigModal,
  testSingleChannel,
} from '../components/management/notifications.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const byId = (id) => document.getElementById(id);

describe('alert channel words (NUX-20)', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <span id="notif-badge-discord"></span><span id="notif-badge-telegram"></span>
      <div id="modal-notification-channel"><h3 id="notif-modal-title"></h3><div id="notif-modal-body"></div>
        <input type="checkbox" id="notif-modal-channel-enable"></div>`;
    vi.spyOn(api, 'get').mockResolvedValue({ discord_enabled: true, discord_webhook_url: 'https://discord.example/h', smtp_tls: false });
    await fetchAndRenderNotificationConfig();
  });
  afterEach(() => vi.restoreAllMocks());

  it('marks a channel that is not set up as Off', () => {
    expect(byId('notif-badge-discord').textContent).toBe('Active');
    expect(byId('notif-badge-telegram').textContent).toBe('Off');
  });

  it('labels every channel dialog', () => {
    const labels = {
      discord: ['DISCORD WEBHOOK URL', 'Paste the Webhook URL created in your Discord channel settings -> Integrations.'],
      telegram: ['TELEGRAM BOT TOKEN', 'TELEGRAM CHAT ID', 'Obtained from @userinfobot'],
      email: ['SMTP HOST', 'SMTP USER', 'SMTP PASSWORD', 'FROM EMAIL', 'TO RECIPIENT(S)', 'Use TLS / STARTTLS Encryption'],
      ntfy: ['NTFY SERVER URL', 'TOPIC NAME', 'ACCESS TOKEN (Optional)'],
      webhook: ['WEBHOOK URL', 'Receives POST requests with JSON payload'],
      apprise_raw: ['APPRISE TARGET URLS (One per line)', 'Apprise supports 100+ notification targets.'],
    };
    for (const [channel, words] of Object.entries(labels)) {
      openChannelConfigModal(channel);
      const body = byId('notif-modal-body').textContent;
      for (const w of words) expect(body).toContain(w);
    }
    expect(byId('notif-modal-title').textContent).toBe('Configure Apprise Alerts');
    openChannelConfigModal('email');
    expect(byId('cfg-smtp-tls').checked).toBe(false);
  });

  it('ticks TLS when the settings ask for it', async () => {
    api.get.mockResolvedValue({ smtp_tls: true });
    await fetchAndRenderNotificationConfig();
    openChannelConfigModal('email');
    expect(byId('cfg-smtp-tls').checked).toBe(true);
  });

  it('says why a test message was not delivered', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: false, message: 'bad URL' });
    await testSingleChannel('discord');
    expect(showToast).toHaveBeenLastCalledWith('⚠️ DISCORD: bad URL', 'error');
    post.mockResolvedValue({ success: false });
    await testSingleChannel('discord');
    expect(showToast).toHaveBeenLastCalledWith('⚠️ DISCORD: Delivery failed', 'error');
  });
});
