import { describe, it, expect, beforeEach, vi } from 'vitest';
import fs from 'fs';
import path from 'path';
import { SUBPANE_MAP, openChannelConfigModal, renderNotificationConfigUI } from '../components/management.js';

describe('Notifications & Multi-Channel Alerting UI Integration', () => {
  let html;

  beforeEach(() => {
    const htmlPath = path.resolve(__dirname, '../../index.html');
    html = fs.readFileSync(htmlPath, 'utf8');
  });

  it('verifies Notifications & Alerts inner tab exists in System section of index.html', () => {
    expect(html).toContain('id="mgmt-tab-notifications"');
    expect(html).toContain('data-tab-target="mgmt-pane-notifications"');
    expect(html).toContain('data-i18n="mgmt.subtab_notifications"');
  });

  it('verifies mgmt-pane-notifications contains all 6 channel cards and master toggle', () => {
    expect(html).toContain('id="mgmt-pane-notifications"');
    expect(html).toContain('id="notif-master-enabled"');
    expect(html).toContain('id="notif-master-status-badge"');
    expect(html).toContain('id="btn-send-test-alert"');
    expect(html).toContain('id="btn-save-notifications"');

    // All 6 channels
    expect(html).toContain('data-channel="discord"');
    expect(html).toContain('data-channel="telegram"');
    expect(html).toContain('data-channel="email"');
    expect(html).toContain('data-channel="ntfy"');
    expect(html).toContain('data-channel="webhook"');
    expect(html).toContain('data-channel="apprise_raw"');

    // Channel status badges
    expect(html).toContain('id="notif-badge-discord"');
    expect(html).toContain('id="notif-badge-telegram"');
    expect(html).toContain('id="notif-badge-email"');
    expect(html).toContain('id="notif-badge-ntfy"');
    expect(html).toContain('id="notif-badge-webhook"');
    expect(html).toContain('id="notif-badge-apprise"');
  });

  it('verifies all subsystem event triggers and threshold controls exist in index.html', () => {
    expect(html).toContain('id="notif-toggle-smart"');
    expect(html).toContain('id="notif-toggle-temp"');
    expect(html).toContain('id="notif-toggle-ups"');
    expect(html).toContain('id="notif-toggle-fan"');
    expect(html).toContain('id="notif-toggle-copy"');
    expect(html).toContain('id="notif-toggle-container"');
    expect(html).toContain('id="notif-toggle-backup"');

    expect(html).toContain('id="notif-input-hdd-temp"');
    expect(html).toContain('id="notif-input-cpu-temp"');
    expect(html).toContain('id="notif-input-cooldown"');
  });

  it('verifies channel configuration modal and dock settings button exist', () => {
    expect(html).toContain('id="modal-notification-channel"');
    expect(html).toContain('id="notif-modal-title"');
    expect(html).toContain('id="notif-modal-channel-enable"');
    expect(html).toContain('id="notif-modal-body"');
    expect(html).toContain('id="btn-save-channel-modal"');
    expect(html).toContain('id="notif-settings-btn"');
  });

  it('verifies SUBPANE_MAP correctly routes notifications to System group', () => {
    expect(SUBPANE_MAP['mgmt-pane-notifications']).toEqual({
      section: 'mgmt-sec-system-group',
      pane: 'mgmt-pane-notifications'
    });
    expect(SUBPANE_MAP['mgmt-sec-notifications']).toEqual({
      section: 'mgmt-sec-system-group',
      pane: 'mgmt-pane-notifications'
    });
  });

  it('verifies openChannelConfigModal populates channel specific inputs correctly', () => {
    document.body.innerHTML = `
      <div id="modal-notification-channel" style="display:none;">
        <span id="notif-modal-title"></span>
        <input type="checkbox" id="notif-modal-channel-enable">
        <div id="notif-modal-body"></div>
      </div>
    `;

    openChannelConfigModal('discord');
    expect(document.getElementById('notif-modal-title').textContent).toContain('Discord');
    expect(document.getElementById('cfg-discord-url')).not.toBeNull();

    openChannelConfigModal('telegram');
    expect(document.getElementById('notif-modal-title').textContent).toContain('Telegram');
    expect(document.getElementById('cfg-telegram-token')).not.toBeNull();
    expect(document.getElementById('cfg-telegram-chat')).not.toBeNull();

    openChannelConfigModal('email');
    expect(document.getElementById('notif-modal-title').textContent).toContain('Email');
    expect(document.getElementById('cfg-smtp-host')).not.toBeNull();
    expect(document.getElementById('cfg-smtp-port')).not.toBeNull();

    openChannelConfigModal('ntfy');
    expect(document.getElementById('notif-modal-title').textContent).toContain('Ntfy');
    expect(document.getElementById('cfg-ntfy-topic')).not.toBeNull();
  });
});
