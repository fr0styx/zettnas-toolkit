/**
 * Home Assistant (RES-5): the card in Network → File Sharing Services that sends Kiboto's health to
 * Home Assistant as sensors, through the MQTT broker Home Assistant uses (MQTT discovery).
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';
import { formatDateTime } from '../../format.js';
import { showToast } from '../../toast.js';

export function haStatus(cfg) {
  const st = cfg?.status || {};
  if (!cfg?.enabled) return t('ha.off', 'Off. Set the broker Home Assistant uses, then turn it on.');
  if (st.last_ok === false) return t('ha.failed', "The last send didn't reach the broker: {error}", { error: st.last_error || '' });
  if (st.last_ok) return t('ha.ok', '{count, plural, one {# sensor sent} other {# sensors sent}}, last at {when}.', { count: st.sensors || 0, when: formatDateTime((st.last_at || 0) * 1000) });
  return t('ha.waiting', 'On: the first send comes within a minute.');
}

export function haCardHtml(cfg) {
  const c = cfg || {};
  const pw = c.has_password ? t('ha.password_saved', 'Saved: leave empty to keep it') : '';
  return `<div class="nsv-row-3"><div class="nsv-row-4"><span class="nsv-fs18" aria-hidden="true">🏠</span><div>
      <strong>${escapeHtml(t('ha.title', 'Home Assistant'))}</strong>
      <div class="immich-note" data-ha-status>${escapeHtml(haStatus(c))}</div></div></div>
      <button type="button" class="btn-pill-toggle${c.enabled ? ' active' : ''}" data-ha-toggle aria-pressed="${c.enabled ? 'true' : 'false'}">${escapeHtml(c.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'))}</button></div>
    <p class="immich-note">${escapeHtml(t('ha.desc', 'Sends CPU, memory, disk temperatures, the UPS and the ransomware guard to Home Assistant as sensors, through its MQTT broker (Mosquitto). They show up on their own under MQTT devices.'))}</p>
    <form class="immich-form" data-ha-form>
      <label>${escapeHtml(t('ha.host', 'Broker address'))}<input name="host" value="${escapeHtml(c.host || '')}" placeholder="homeassistant.local" autocomplete="off"></label>
      <label>${escapeHtml(t('ha.port', 'Port'))}<input name="port" type="number" min="1" max="65535" value="${escapeHtml(String(c.port || 1883))}"></label>
      <label>${escapeHtml(t('ha.username', 'User name'))}<input name="username" value="${escapeHtml(c.username || '')}" autocomplete="off"></label>
      <label>${escapeHtml(t('ha.password', 'Password'))}<input name="password" type="password" placeholder="${escapeHtml(pw)}" autocomplete="new-password"></label>
      <label><input name="tls" type="checkbox"${c.tls ? ' checked' : ''}> ${escapeHtml(t('ha.tls', 'Encrypted (TLS)'))}</label>
      <div class="nsv-row-2"><button type="submit" class="btn-pill-toggle is-primary">${escapeHtml(t('common.save', 'Save'))}</button>
      <button type="button" class="btn-pill-toggle" data-ha-test>${escapeHtml(t('ha.test', 'Send now'))}</button></div>
    </form>`;
}

export function haFormValues(form) {
  const data = new FormData(form);
  const out = {
    host: String(data.get('host') || '').trim(),
    port: Number(data.get('port') || 1883),
    username: String(data.get('username') || ''),
    tls: data.get('tls') === 'on',
  };
  const pw = String(data.get('password') || '');
  if (pw) out.password = pw; // empty: keep the saved one
  return out;
}

export async function loadHomeAssistantCard() {
  const grid = document.getElementById('notif-ha-grid') || document.getElementById('network-services-grid'); // on Notifications since SET-24
  if (!grid) return;
  let card = document.getElementById('ha-card');
  if (!card) {
    card = document.createElement('div');
    card.id = 'ha-card';
    card.className = 'nsv-col-box';
    grid.appendChild(card);
  }
  let cfg;
  try {
    cfg = await api.get('/api/integrations/home-assistant');
  } catch {
    card.hidden = true; // not an administrator
    return;
  }
  const render = (next) => {
    cfg = next;
    card.hidden = false;
    card.innerHTML = haCardHtml(cfg);
  };
  render(cfg);
  if (card.dataset.bound) return;
  card.dataset.bound = '1';
  const put = async (changes, okText) => {
    try {
      render(await api.put('/api/integrations/home-assistant', changes));
      if (okText) showToast(okText, 'success');
      return true;
    } catch (err) {
      showToast(/** @type {Error} */ (err).message, 'error');
      return false;
    }
  };
  card.addEventListener('submit', (e) => {
    e.preventDefault();
    const form = /** @type {HTMLFormElement} */ (e.target);
    put(haFormValues(form), t('ha.saved', 'Saved.'));
  });
  card.addEventListener('click', async (e) => {
    const target = /** @type {Element} */ (e.target);
    if (target.closest('[data-ha-toggle]')) {
      await put({ enabled: !cfg.enabled });
    } else if (target.closest('[data-ha-test]')) {
      const form = /** @type {HTMLFormElement | null} */ (card.querySelector('[data-ha-form]'));
      if (form && !(await put(haFormValues(form)))) return;
      try {
        const res = await api.post('/api/integrations/home-assistant/test', {});
        showToast(t('ha.test_ok', '{count, plural, one {# sensor sent} other {# sensors sent}} to Home Assistant.', { count: res?.sensors || 0 }), 'success');
      } catch (err) {
        showToast(/** @type {Error} */ (err).message, 'error');
      }
      render(await api.get('/api/integrations/home-assistant'));
    }
  });
}
