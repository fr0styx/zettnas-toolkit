// Network: "This NAS at home" and "Network ports" (SET-24 m). Plain sentences and one row per port,
// in place of three tiles, a drawn switch and a 10-column table (network report, section 4).
import { escapeHtml, copyText } from '../../utils.js';
import { formatBytes as formatSize } from '../../format.js';
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';

const known = (v) => (v ? String(v) : t('net.unknown', 'Unknown'));

/** A translated sentence with one value in bold: the value is never part of the translation. */
function withValue(key, english, name, value) {
  const [before, after = ''] = t(key, english, { [name]: '\u0001' }).split('\u0001');
  return `${escapeHtml(before)}<strong translate="no">${escapeHtml(value)}</strong>${escapeHtml(after)}`;
}

/** Where the NAS answers at home; the router, name servers and port under Details. */
export function homeHtml(summary = {}) {
  const ip = summary.primary_ip === '?' ? '' : summary.primary_ip; // the host's mark for 'not found'
  if (!ip) return `<p class="net-home-line">${escapeHtml(t('net.home_unknown', "Kiboto could not read this NAS's address."))}</p>`;
  const dns = (summary.dns_servers || []).filter(Boolean).join(', ');
  return `<p class="net-home-line"><span>${withValue('net.home_at', 'At home, this NAS answers at {address}.', 'address', ip)}</span>
      <button type="button" class="btn-pill-toggle is-small" data-copy="${escapeHtml(ip)}">${escapeHtml(t('net.home_copy', 'Copy'))}</button></p>
    <p class="net-home-hint">${escapeHtml(t('net.home_reserve', 'To keep this address, reserve it for the NAS in your router.'))}</p>
    <details class="net-home-details">
      <summary>${escapeHtml(t('net.details', 'Details'))}</summary>
      <dl class="net-dl">
        <dt>${escapeHtml(t('net.home_router', 'Router'))}</dt><dd>${escapeHtml(known(summary.default_gateway))}</dd>
        <dt>${escapeHtml(t('net.home_dns', 'Name servers'))}</dt><dd>${escapeHtml(known(dns))}</dd>
        <dt>${escapeHtml(t('net.home_port', 'Through'))}</dt><dd>${escapeHtml(known(summary.primary_interface))}</dd>
      </dl>
      <button type="button" class="btn-pill-toggle is-small" id="btn-open-host-ip-modal">${escapeHtml(t('net.home_settings', 'Address settings'))}</button>
    </details>`;
}

/** One row per port: its name, Connected or Not connected (a word, not only a colour), the speed;
 *  the hardware address, driver, bond and traffic under Details, with "Name this port". */
export function portRowsHtml(physical = []) {
  if (!physical.length) return `<li class="net-port-empty">${escapeHtml(t('net.no_nics', 'No network ports found.'))}</li>`;
  return physical
    .map((nic) => {
      const up = Boolean(nic.is_up);
      const name = nic.alias ? `${nic.alias} (${nic.name})` : nic.name;
      const state = up ? t('net.port_connected', 'Connected') : t('net.port_not_connected', 'Not connected');
      const speed = up && nic.speed_human && nic.speed_human !== 'Disconnected' ? nic.speed_human : ''; // the host's word for down
      const traffic = nic.rx_bytes || nic.tx_bytes ? `${formatSize(nic.rx_bytes || 0)} / ${formatSize(nic.tx_bytes || 0)}` : '';
      const facts = [
        [t('net.port_mac', 'Hardware address'), nic.mac],
        [t('net.port_driver', 'Driver'), nic.driver],
        [t('net.port_part_of', 'Part of'), nic.master],
        [t('net.port_traffic', 'Received / sent'), traffic],
      ].filter(([, v]) => v);
      return `<li class="net-port-row ${up ? 'is-up' : 'is-down'}" data-iface="${escapeHtml(nic.name)}">
        <span class="net-port-name">${escapeHtml(name)}</span>
        <span class="net-port-state"><span class="net-port-dot" aria-hidden="true"></span>${escapeHtml(state)}</span>
        <span class="net-port-speed">${escapeHtml(speed)}</span>
        <details class="net-port-details"><summary>${escapeHtml(t('net.details', 'Details'))}</summary>
          <dl class="net-dl">${facts.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd>`).join('')}</dl>
          <button type="button" class="btn-pill-toggle is-small" data-name-port="${escapeHtml(nic.name)}">${escapeHtml(t('net.port_name_btn', 'Name this port'))}</button>
        </details>
      </li>`;
    })
    .join('');
}

/** Network's Tailscale options show while Tailscale is connected; otherwise one sentence with a
 *  link to Away from home (SET-24 n: they were in Away from home's Tailscale details). */
export function showTailscaleOptions(on, doc = document) {
  const opts = doc.getElementById('net-ts-opts');
  const off = doc.getElementById('net-ts-off');
  if (opts) opts.hidden = !on;
  if (off) off.hidden = on;
}

/** Fills This NAS at home; Copy copies the address. */
export function renderHome(box, summary) {
  if (!box) return;
  box.innerHTML = homeHtml(summary);
  const copy = /** @type {HTMLElement | null} */ (box.querySelector('[data-copy]'));
  copy?.addEventListener('click', () =>
    copyText(copy.dataset.copy || '')
      .then(() => showToast(t('net.home_copied', 'Address copied.'), 'success'))
      .catch(() => showToast(t('net.home_copy_failed', 'Could not copy. Select the address and copy it yourself.'), 'error')),
  );
}

/** Fills the port rows; "Name this port" calls onName with the port. */
export function renderPortRows(list, physical, onName) {
  if (!list) return;
  list.innerHTML = portRowsHtml(physical);
  list.querySelectorAll('[data-name-port]').forEach((btn) => btn.addEventListener('click', () => onName(/** @type {HTMLElement} */ (btn).dataset.namePort || '')));
}
