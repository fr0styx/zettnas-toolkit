/**
 * The Security and Notifications tabs hold an administrator's set-up beside each person's own
 * things (SET-03). For anyone but an administrator the set-up is not drawn and not asked for;
 * what is theirs (their data, their devices) loads for everyone.
 */
import { hideAdminOnly } from '../../admin-only.js';
import { fetchAndRenderSecurityPosture } from './security.js';
import { fetchAndRenderNotificationConfig } from './notifications.js';

/** @returns {boolean} true when the administrator's part was loaded too */
export function loadSecurityPane() {
  const adminToo = !hideAdminOnly(document.getElementById('mgmt-pane-security'));
  if (adminToo) {
    import('../settings.js').then((m) => m.renderApiTokens && m.renderApiTokens()).catch(() => {});
    import('../guard-panel.js').then((m) => m.renderGuardPanel()).catch(() => {});
    import('../file-activity.js').then((m) => m.renderFileActivity()).catch(() => {}); // FEAT-12
    import('../sso.js').then((m) => { m.renderSsoPanel(); m.renderLdapPanel(); }).catch(() => {});
    fetchAndRenderSecurityPosture();
  }
  import('./user-data.js').then((m) => m.installMyData()).catch(() => {}); // your data (B8)
  return adminToo;
}

/** @returns {boolean} true when the administrator's part was loaded too */
export function loadNotificationsPane() {
  const adminToo = !hideAdminOnly(document.getElementById('mgmt-pane-notifications'));
  if (adminToo) fetchAndRenderNotificationConfig();
  import('../push-card.js').then((m) => m.renderPushCard()).catch(() => {});
  return adminToo;
}
