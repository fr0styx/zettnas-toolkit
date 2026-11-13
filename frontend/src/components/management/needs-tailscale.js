/**
 * "Needs Tailscale", with a button that opens Network → Remote access, where it is connected
 * (SET-16). The cards that need Tailscale (share links, apps, family, fleet) use it.
 */
import { t } from '../../i18n.js';

/** @param {(s: string) => string} esc */
export function needsTailscaleHtml(esc) {
  return `<div class="nsv-xs-muted">${esc(t('pl.no_tailscale', 'Needs Tailscale.'))} <button type="button" class="btn-pill-toggle is-small" data-open-remote-access>${esc(t('pl.connect_tailscale', 'Connect Tailscale'))}</button></div>`;
}

/** Opens Network → Remote access. */
export function openRemoteAccess() {
  const open = /** @type {any} */ (window).openManagementWindow;
  if (typeof open === 'function') open('mgmt-sec-away', 'mgmt-pane-network-wireguard');
}

let _installed = false;
/** One listener for every such button, whenever the card is drawn. */
export function installNeedsTailscale(doc = document) {
  if (_installed) return;
  _installed = true;
  doc.addEventListener('click', (e) => {
    const btn = e.target instanceof Element ? e.target.closest('[data-open-remote-access]') : null;
    if (btn) openRemoteAccess();
  });
}
