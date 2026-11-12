/**
 * What this host lets Kiboto change on its network (SET-16, decision D2). On Unraid and the other
 * hosts Kiboto does not manage, the host's own settings own the wiring: the page shows it and says
 * where to change it. On Kiboto's own OS images the same rows become fields again.
 * The capabilities arrive with the network layout (GET /api/system/network-topology, "host").
 */
import { t } from '../../i18n.js';

/** Until the layout has loaded, nothing is changeable. */
export const READ_ONLY = Object.freeze({ managed: false, where: 'system', can_change: {} });
let _caps = READ_ONLY;

export function setNetCaps(caps) {
  _caps = caps && typeof caps === 'object' ? caps : READ_ONLY;
}

export function netCaps() {
  return _caps;
}

export function canChange(setting, caps = _caps) {
  return Boolean(caps?.can_change?.[setting]);
}

const WHERE = {
  unraid: () => t('net.where_unraid', 'Unraid, under Settings → Network Settings'),
  truenas: () => t('net.where_truenas', 'TrueNAS, under Network'),
  proxmox: () => t('net.where_proxmox', "Proxmox, under the node's System → Network"),
  ugos: () => t('net.where_ugos', 'UGOS, under Control Panel → Network'),
  system: () => t('net.where_system', "the host system's own network settings"),
};

/** "This is set up in Unraid, under Settings → Network Settings. Kiboto shows it but does not change it." */
export function hostNote(caps = _caps) {
  const where = (WHERE[caps?.where] || WHERE.system)();
  return t('net.set_on_host', 'This is set up in {where}. Kiboto shows it but does not change it.', { where });
}

/**
 * Marks what may not change here: [data-net-setting] fields go read-only, [data-net-edit] buttons
 * hide, and a .net-host-note (data-net-for="mtu speed …") says where to change it.
 */
/**
 * @param {ParentNode | null} [root]
 * @param {any} [caps]
 */
export function applyNetCaps(root = document, caps = _caps) {
  if (!root) return;
  /** @type {NodeListOf<HTMLElement>} */ (root.querySelectorAll('[data-net-setting]')).forEach((el) => {
    const ok = canChange(el.dataset.netSetting, caps);
    const fields = el.matches('input, select, button, textarea') ? [el] : Array.from(el.querySelectorAll('input, select, button, textarea'));
    fields.forEach((f) => {
      /** @type {HTMLInputElement} */ (f).disabled = !ok;
    });
    el.classList.toggle('is-readonly', !ok);
  });
  /** @type {NodeListOf<HTMLElement>} */ (root.querySelectorAll('[data-net-edit]')).forEach((el) => {
    el.style.display = canChange(el.dataset.netEdit, caps) ? '' : 'none';
  });
  /** @type {NodeListOf<HTMLElement>} */ (root.querySelectorAll('.net-host-note')).forEach((el) => {
    const settings = (el.dataset.netFor || '').split(' ').filter(Boolean);
    const readOnly = settings.some((s) => !canChange(s, caps));
    el.hidden = !readOnly;
    if (readOnly) el.textContent = hostNote(caps);
  });
}

/** What the port dialog sends: the nickname always, the wiring only where this host lets Kiboto change it. */
export function portPayload(values, caps = _caps) {
  const out = { alias: values.alias };
  if (canChange('mtu', caps)) out.mtu = values.mtu;
  if (canChange('wake_on_lan', caps)) out.wol_enabled = values.wol_enabled;
  if (canChange('speed', caps)) {
    out.autoneg = values.autoneg;
    out.speed = values.speed;
    out.duplex = 'full';
  }
  return out;
}
