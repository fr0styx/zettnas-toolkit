/**
 * Mission Control: Notification channels.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { SUPPORTED_LANGUAGES } from '../../i18n.js';
import { setIconLabel } from '../../ui/primitives.js';
import { api } from '../../api.js';
import { showToast } from '../../toast.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { renderMyAlerts } from '../my-alerts.js';

// ============================================================================
// Notifications & Alert Channels Subsystem
// ============================================================================
let _notificationConfig = null;

export async function fetchAndRenderNotificationConfig() {
  try {
    const res = await api.get('/api/notifications/config');
    _notificationConfig = res || {};
    renderNotificationConfigUI();
  } catch (err) {
    console.error('Failed to load notification config:', err);
    showToast(t('notif.load_fail', 'Failed to load notification settings'), 'error');
  }
}

export function renderNotificationConfigUI() {
  if (!_notificationConfig) return;
  const cfg = _notificationConfig;
  const digestMode = document.getElementById('notif-digest-mode');
  if (digestMode) digestMode.value = cfg.digest_mode === 'daily' ? 'daily' : 'off';
  const digestHour = document.getElementById('notif-digest-hour');
  if (digestHour) digestHour.value = String(cfg.digest_hour ?? 8);
  const weekly = document.getElementById('notif-weekly-report');
  if (weekly) weekly.checked = cfg.weekly_report !== false;
  const lang = /** @type {HTMLSelectElement | null} */ (document.getElementById('notif-language'));
  if (lang) {
    // the household's language for pushes and e-mails (NUX-3); each language under its own name
    if (!lang.options.length) {
      for (const l of SUPPORTED_LANGUAGES) lang.append(Object.assign(document.createElement('option'), { value: l.code, textContent: l.name, lang: l.code }));
    }
    lang.value = cfg.language || 'en';
  }
  renderMyAlerts(document.getElementById('my-alerts-mount'));
  installSaveAtOnce();
  const frigate = document.getElementById('frigate-events-mount');
  if (frigate) import('../frigate-events.js').then((m) => m.renderFrigateEvents(frigate)); // COMP-11

  // Master switch
  const masterSwitch = document.getElementById('notif-master-enabled');
  const masterBadge = document.getElementById('notif-master-status-badge');
  if (masterSwitch) masterSwitch.checked = !!cfg.enabled;
  if (masterBadge) {
    masterBadge.textContent = cfg.enabled ? t('notif.badge.active', 'Active') : t('notif.badge.disabled', 'Disabled');
    masterBadge.style.background = cfg.enabled ? 'rgba(51,205,184,0.15)' : 'rgba(255,255,255,0.06)';
    masterBadge.style.color = cfg.enabled ? 'var(--ok2)' : 'var(--muted)';
    masterBadge.style.border = cfg.enabled ? '1px solid rgba(51,205,184,0.4)' : '1px solid rgba(255,255,255,0.1)';
  }

  // Channel badges
  const updateBadge = (id, active, activeText = t('notif.badge.active', 'Active')) => {
    const b = document.getElementById(id);
    if (!b) return;
    b.textContent = active ? activeText : t('ntf.off', 'Off');
    b.style.background = active ? 'rgba(51,205,184,0.15)' : 'rgba(255,255,255,0.06)';
    b.style.color = active ? 'var(--ok2)' : 'var(--muted)';
    b.style.border = active ? '1px solid rgba(51,205,184,0.4)' : '1px solid rgba(255,255,255,0.1)';
  };

  updateBadge('notif-badge-discord', !!(cfg.discord_enabled && cfg.discord_webhook_url));
  updateBadge('notif-badge-telegram', !!(cfg.telegram_enabled && cfg.telegram_bot_token && cfg.telegram_chat_id));
  updateBadge('notif-badge-email', !!(cfg.email_enabled && cfg.smtp_host));
  updateBadge('notif-badge-ntfy', !!(cfg.ntfy_enabled && cfg.ntfy_topic));
  updateBadge('notif-badge-webhook', !!(cfg.webhook_enabled && cfg.webhook_url));

  const rawCount = Array.isArray(cfg.apprise_urls) ? cfg.apprise_urls.length : 0;
  updateBadge('notif-badge-apprise', rawCount > 0 && cfg.apprise_enabled !== false, t('ntf.url_count', '{count, plural, one {# URL} other {# URLs}}', { count: rawCount }));

  // Event trigger checkboxes
  const setChk = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.checked = val !== false;
  };
  setChk('notif-toggle-smart', cfg.notify_on_smart);
  setChk('notif-toggle-ups', cfg.notify_on_ups);
  setChk('notif-toggle-temp', cfg.notify_on_temp);
  setChk('notif-toggle-fan', cfg.notify_on_fan);
  setChk('notif-toggle-copy', cfg.notify_on_copy);
  setChk('notif-toggle-backup', cfg.notify_on_backup);

  // Thresholds
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el && val !== undefined) el.value = val;
  };
  setVal('notif-input-hdd-temp', cfg.hdd_temp_threshold ?? 50);
  setVal('notif-input-cpu-temp', cfg.cpu_temp_threshold ?? 80);
  setVal('notif-input-cooldown', Math.round((cfg.cooldown_seconds ?? 1800) / 60));
}

// the fields that save themselves when they change (SET-14): they waited for "Save Settings" at
// the top of the page, and leaving the page lost the change without a word
export const SAVED_AT_ONCE = [
  'notif-master-enabled',
  'notif-toggle-smart',
  'notif-toggle-ups',
  'notif-toggle-temp',
  'notif-toggle-fan',
  'notif-toggle-copy',
  'notif-toggle-backup',
  'notif-input-hdd-temp',
  'notif-input-cpu-temp',
  'notif-input-cooldown',
  'notif-digest-mode',
  'notif-digest-hour',
  'notif-weekly-report',
  'notif-language',
];
let _saveTimer = null;

/** Each field saves the settings when it changes; numbers once typing has paused. */
export function installSaveAtOnce(root = document, wait = 500) {
  for (const id of SAVED_AT_ONCE) {
    const el = root.getElementById ? root.getElementById(id) : null;
    if (!el || el.dataset.savesAtOnce) continue;
    el.dataset.savesAtOnce = '1';
    el.addEventListener('change', () => {
      clearTimeout(_saveTimer);
      _saveTimer = setTimeout(() => saveNotificationsConfig({ quiet: true }), wait);
    });
  }
}

export async function saveNotificationsConfig({ quiet = false } = {}) {
  if (!_notificationConfig) _notificationConfig = {};
  const cfg = _notificationConfig;

  cfg.enabled = !!document.getElementById('notif-master-enabled')?.checked;
  cfg.notify_on_smart = !!document.getElementById('notif-toggle-smart')?.checked;
  cfg.notify_on_ups = !!document.getElementById('notif-toggle-ups')?.checked;
  cfg.notify_on_temp = !!document.getElementById('notif-toggle-temp')?.checked;
  cfg.notify_on_fan = !!document.getElementById('notif-toggle-fan')?.checked;
  cfg.notify_on_copy = !!document.getElementById('notif-toggle-copy')?.checked;
  cfg.notify_on_backup = !!document.getElementById('notif-toggle-backup')?.checked;

  const hdd = parseInt(document.getElementById('notif-input-hdd-temp')?.value, 10);
  if (!isNaN(hdd)) cfg.hdd_temp_threshold = Math.max(30, Math.min(80, hdd));

  const cpu = parseInt(document.getElementById('notif-input-cpu-temp')?.value, 10);
  if (!isNaN(cpu)) cfg.cpu_temp_threshold = Math.max(40, Math.min(105, cpu));

  const cd = parseInt(document.getElementById('notif-input-cooldown')?.value, 10);
  if (!isNaN(cd)) cfg.cooldown_seconds = Math.max(1, Math.min(1440, cd)) * 60;

  cfg.digest_mode = document.getElementById('notif-digest-mode')?.value === 'daily' ? 'daily' : 'off';
  const dh = parseInt(document.getElementById('notif-digest-hour')?.value, 10);
  if (!isNaN(dh)) cfg.digest_hour = Math.max(0, Math.min(23, dh));
  const weekly = document.getElementById('notif-weekly-report');
  if (weekly) cfg.weekly_report = weekly.checked;
  const lang = /** @type {HTMLSelectElement | null} */ (document.getElementById('notif-language'));
  if (lang && lang.value) cfg.language = lang.value;

  try {
    const res = await api.post('/api/notifications/config', cfg);
    _notificationConfig = res.config || cfg;
    renderNotificationConfigUI();
    showToast(quiet ? t('notif.saved_short', 'Saved.') : t('notif.saved_ok', 'Notification settings saved successfully!'), 'success');
  } catch (err) {
    console.error('Failed to save notification settings:', err);
    showToast(err.message || t('notif.save_fail', 'Failed to save the notification settings'), 'error');
  }
}

export async function testAllNotificationChannels() {
  const btn = document.getElementById('btn-send-test-alert');
  if (btn) {
    btn.disabled = true;
    setIconLabel(btn, '⏳', t('ui.testing_2', 'Testing...'));
  }
  try {
    const res = await api.post('/api/notifications/test', {});
    const channels = res?.tested_channels || {};
    const successList = Object.keys(channels).filter(k => channels[k]);
    if (successList.length > 0) {
      showToast(t('toast.test_alerts_delivered_to', '✓ Test alerts delivered to: {successList}', { successList: successList.join(', ') }), 'success');
    } else {
      showToast(t('toast.no_active_channels_succeeded_check_configuration', 'No active channels succeeded. Check configuration and credentials.'), 'warning');
    }
  } catch (err) {
    showToast(t('toast.test_failed', 'Test failed: {error}', { error: err.message }), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '⚡ <span data-i18n="mgmt.notif_btn_test_all">' + escapeHtml(t('mgmt.notif_btn_test_all', 'Send Test Alert')) + '</span>';
    }
  }
}

export async function testSingleChannel(channel) {
  const btn = document.querySelector(`.notif-test-btn[data-channel="${channel}"]`);
  const origText = btn ? btn.textContent : '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳';
  }
  try {
    const res = await api.post('/api/notifications/test-channel', {
      channel: channel,
      config: _notificationConfig || {}
    });
    if (res?.success) {
      showToast(t('toast.delivered_in_ms', '✓ {channel}: Delivered in {latency_ms}ms', { channel: channel.toUpperCase(), latency_ms: res.latency_ms }), 'success');
    } else {
      showToast(t('toast.message', '{channel}: {message}', { channel: channel.toUpperCase(), message: res.message || t('ntf.delivery_failed', 'Delivery failed') }), 'error');
    }
  } catch (err) {
    showToast(t('toast.test_failed_for', 'Test failed for {channel}: {error}', { channel: channel, error: err.message }), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = origText;
    }
  }
}

export function openChannelConfigModal(channel) {
  const modal = document.getElementById('modal-notification-channel');
  if (!modal) return;
  const cfg = _notificationConfig || {};

  const titleEl = document.getElementById('notif-modal-title');
  const bodyEl = document.getElementById('notif-modal-body');
  const enableChk = document.getElementById('notif-modal-channel-enable');

  if (titleEl) titleEl.textContent = t('ntf.configure', 'Configure {channel} Alerts', { channel: channel.replace(/_raw$/, '').replace(/^./, (c) => c.toUpperCase()) });

  let formHtml = '';
  if (channel === 'discord') {
    if (enableChk) enableChk.checked = !!cfg.discord_enabled;
    formHtml = `
      <div class="ntf-x">
        <label class="ntf-xs-bold-muted" for="cfg-discord-url">${t('ntf.discord_url', 'DISCORD WEBHOOK URL')}</label>
        <input type="url" id="cfg-discord-url" class="tz-select-input ntf-strong-box" placeholder="https://discord.com/api/webhooks/..." value="${escapeHtml(cfg.discord_webhook_url || '')}">
        <div class="ntf-xs-muted">${t('ntf.discord_hint', 'Paste the Webhook URL created in your Discord channel settings -> Integrations.')}</div>
      </div>
    `;
  } else if (channel === 'telegram') {
    if (enableChk) enableChk.checked = !!cfg.telegram_enabled;
    formHtml = `
      <div class="ntf-x">
        <label class="ntf-xs-bold-muted" for="cfg-telegram-token">${t('ntf.tg_bot', 'TELEGRAM BOT TOKEN')}</label>
        <input type="password" id="cfg-telegram-token" class="tz-select-input ntf-strong-box" placeholder="123456789:ABCDefgh..." data-sample value="${escapeHtml(cfg.telegram_bot_token || '')}">
      </div>
      <div class="ntf-x">
        <label class="ntf-xs-bold-muted" for="cfg-telegram-chat">${t('ntf.tg_chat', 'TELEGRAM CHAT ID')}</label>
        <input type="text" id="cfg-telegram-chat" class="tz-select-input ntf-strong-box" placeholder="-100123456789" value="${escapeHtml(cfg.telegram_chat_id || '')}">
        <div class="ntf-xs-muted">${t('ntf.tg_hint', 'Obtained from @userinfobot or your Telegram channel/group chat ID.')}</div>
      </div>
    `;
  } else if (channel === 'email') {
    if (enableChk) enableChk.checked = !!cfg.email_enabled;
    formHtml = `
      <div class="ntf-grid">
        <div>
          <label class="ntf-xs-bold-muted" for="cfg-smtp-host">${t('ntf.smtp_host', 'SMTP HOST')}</label>
          <input type="text" id="cfg-smtp-host" class="tz-select-input ntf-strong-box" placeholder="smtp.gmail.com" value="${escapeHtml(cfg.smtp_host || '')}">
        </div>
        <div>
          <label class="ntf-xs-bold-muted" for="cfg-smtp-port">${t('ntf.port', 'PORT')}</label>
          <input type="number" id="cfg-smtp-port" class="tz-select-input ntf-strong-box" value="${cfg.smtp_port || 587}">
        </div>
      </div>
      <div class="ntf-grid-2">
        <div>
          <label class="ntf-xs-bold-muted" for="cfg-smtp-user">${t('ntf.smtp_user', 'SMTP USER')}</label>
          <input type="text" id="cfg-smtp-user" class="tz-select-input ntf-strong-box" placeholder="user@domain.com" value="${escapeHtml(cfg.smtp_user || '')}">
        </div>
        <div>
          <label class="ntf-xs-bold-muted" for="cfg-smtp-pass">${t('ntf.smtp_pw', 'SMTP PASSWORD')}</label>
          <input type="password" id="cfg-smtp-pass" class="tz-select-input ntf-strong-box" placeholder="••••••••" value="${escapeHtml(cfg.smtp_pass || '')}">
        </div>
      </div>
      <div class="ntf-grid-2">
        <div>
          <label class="ntf-xs-bold-muted" for="cfg-email-from">${t('ntf.from', 'FROM EMAIL')}</label>
          <input type="email" id="cfg-email-from" class="tz-select-input ntf-strong-box" placeholder="nas@domain.com" value="${escapeHtml(cfg.email_from || '')}">
        </div>
        <div>
          <label class="ntf-xs-bold-muted" for="cfg-email-to">${t('ntf.to', 'TO RECIPIENT(S)')}</label>
          <input type="email" id="cfg-email-to" class="tz-select-input ntf-strong-box" placeholder="admin@domain.com" value="${escapeHtml(cfg.email_to || '')}">
        </div>
      </div>
      <label class="ntf-row-xs-strong">
        <input type="checkbox" id="cfg-smtp-tls" ${cfg.smtp_tls !== false ? 'checked' : ''}> ${t('ntf.tls', 'Use TLS / STARTTLS Encryption')}
      </label>
    `;
  } else if (channel === 'ntfy') {
    if (enableChk) enableChk.checked = !!cfg.ntfy_enabled;
    formHtml = `
      <div class="ntf-x">
        <label class="ntf-xs-bold-muted" for="cfg-ntfy-url">${t('ntf.ntfy_url', 'NTFY SERVER URL')}</label>
        <input type="url" id="cfg-ntfy-url" class="tz-select-input ntf-strong-box" placeholder="https://ntfy.sh" value="${escapeHtml(cfg.ntfy_url || 'https://ntfy.sh')}">
      </div>
      <div class="ntf-x">
        <label class="ntf-xs-bold-muted" for="cfg-ntfy-topic">${t('ntf.topic', 'TOPIC NAME')}</label>
        <input type="text" id="cfg-ntfy-topic" class="tz-select-input ntf-strong-box" placeholder="my_nas_alerts" value="${escapeHtml(cfg.ntfy_topic || '')}">
      </div>
      <div class="ntf-x">
        <label class="ntf-xs-bold-muted" for="cfg-ntfy-token">${t('ntf.ntfy_login', 'ACCESS TOKEN (Optional)')}</label>
        <input type="password" id="cfg-ntfy-token" class="tz-select-input ntf-strong-box" placeholder="tk_••••••••" data-sample value="${escapeHtml(cfg.ntfy_token || '')}">
      </div>
    `;
  } else if (channel === 'webhook') {
    if (enableChk) enableChk.checked = !!cfg.webhook_enabled;
    formHtml = `
      <div class="ntf-x">
        <label class="ntf-xs-bold-muted" for="cfg-webhook-url">${t('ntf.webhook_url', 'WEBHOOK URL')}</label>
        <input type="url" id="cfg-webhook-url" class="tz-select-input ntf-strong-box" placeholder="https://..." value="${escapeHtml(cfg.webhook_url || '')}">
        <div class="ntf-xs-muted">${t('ntf.webhook_hint', 'Receives POST requests with JSON payload: { event, title, message, level, timestamp }')}</div>
      </div>
    `;
  } else if (channel === 'apprise_raw') {
    if (enableChk) /** @type {HTMLInputElement} */ (enableChk).checked = cfg.apprise_enabled !== false;
    const rawVal = Array.isArray(cfg.apprise_urls) ? cfg.apprise_urls.join('\n') : '';
    formHtml = `
      <div class="ntf-x">
        <label class="ntf-xs-bold-muted" for="cfg-apprise-raw">${t('ntf.apprise_urls', 'APPRISE TARGET URLS (One per line)')}</label>
        <textarea id="cfg-apprise-raw" class="tz-select-input ntf-xs-strong-mono-box" placeholder="pover://userkey@token&#10;slack://TokenA/TokenB/TokenC&#10;gotify://gotify.server/token">${escapeHtml(rawVal)}</textarea>
        <div class="ntf-xs-muted">${t('ntf.apprise_hint', 'Apprise supports 100+ notification targets. See Apprise documentation for syntax.')}</div>
      </div>
    `;
  }

  if (bodyEl) bodyEl.innerHTML = formHtml;
  modal.dataset.currentChannel = channel;
  modal.style.display = 'flex';
}

export function saveCurrentChannelModal() {
  const modal = document.getElementById('modal-notification-channel');
  if (!modal) return;
  const channel = modal.dataset.currentChannel;
  if (!_notificationConfig) _notificationConfig = {};
  const cfg = _notificationConfig;
  const enabled = !!document.getElementById('notif-modal-channel-enable')?.checked;

  if (channel === 'discord') {
    cfg.discord_enabled = enabled;
    cfg.discord_webhook_url = document.getElementById('cfg-discord-url')?.value.trim() || '';
  } else if (channel === 'telegram') {
    cfg.telegram_enabled = enabled;
    const tok = document.getElementById('cfg-telegram-token')?.value.trim() || '';
    if (tok && tok !== '********') cfg.telegram_bot_token = tok;
    cfg.telegram_chat_id = document.getElementById('cfg-telegram-chat')?.value.trim() || '';
  } else if (channel === 'email') {
    cfg.email_enabled = enabled;
    cfg.smtp_host = document.getElementById('cfg-smtp-host')?.value.trim() || '';
    cfg.smtp_port = parseInt(document.getElementById('cfg-smtp-port')?.value, 10) || 587;
    cfg.smtp_user = document.getElementById('cfg-smtp-user')?.value.trim() || '';
    const pass = document.getElementById('cfg-smtp-pass')?.value || '';
    if (pass && pass !== '********') cfg.smtp_pass = pass;
    cfg.smtp_tls = !!document.getElementById('cfg-smtp-tls')?.checked;
    cfg.email_from = document.getElementById('cfg-email-from')?.value.trim() || '';
    cfg.email_to = document.getElementById('cfg-email-to')?.value.trim() || '';
  } else if (channel === 'ntfy') {
    cfg.ntfy_enabled = enabled;
    cfg.ntfy_url = document.getElementById('cfg-ntfy-url')?.value.trim() || 'https://ntfy.sh';
    cfg.ntfy_topic = document.getElementById('cfg-ntfy-topic')?.value.trim() || '';
    const tk = document.getElementById('cfg-ntfy-token')?.value.trim() || '';
    if (tk && tk !== '********') cfg.ntfy_token = tk;
  } else if (channel === 'webhook') {
    cfg.webhook_enabled = enabled;
    cfg.webhook_url = document.getElementById('cfg-webhook-url')?.value.trim() || '';
  } else if (channel === 'apprise_raw') {
    cfg.apprise_enabled = enabled;
    const rawLines = document.getElementById('cfg-apprise-raw')?.value.split('\n') || [];
    cfg.apprise_urls = rawLines.map(l => l.trim()).filter(Boolean);
  }

  saveNotificationsConfig();
  modal.style.display = 'none';
}
