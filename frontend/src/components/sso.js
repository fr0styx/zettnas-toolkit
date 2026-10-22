/**
 * Single sign-on (M6): the login-screen button and the admin settings form.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';

export async function initSsoLogin(win = window) {
  const btn = document.getElementById('login-sso-btn');
  const errEl = document.getElementById('login-sso-error');
  const params = new URLSearchParams(win.location.search);
  const err = params.get('sso_error');
  if (err && errEl) {
    errEl.textContent = err;
    errEl.hidden = false;
    params.delete('sso_error');
    const q = params.toString();
    win.history.replaceState(null, '', win.location.pathname + (q ? `?${q}` : ''));
  }
  if (!btn) return;
  try {
    const res = await fetch('/api/auth/oidc/config', { credentials: 'same-origin' });
    const cfg = res.ok ? await res.json() : { enabled: false };
    if (cfg.enabled) {
      btn.textContent = t('login.sso_btn', 'Sign in with {label}', { label: cfg.label || 'SSO' });
      btn.hidden = false;
      btn.onclick = () => {
        win.location.href = '/api/auth/oidc/login';
      };
    }
  } catch (e) {
    console.warn('SSO config unavailable', e);
  }
}

const FIELDS = [
  ['issuer', 'sso.issuer', 'Issuer URL', 'https://auth.example.com/application/o/zettnas'],
  ['client_id', 'sso.client_id', 'Client ID', ''],
  ['client_secret', 'sso.client_secret', 'Client secret', ''],
  ['label', 'sso.label', 'Button label', 'Authentik'],
  ['admin_groups', 'sso.admin_groups', 'Admin groups (comma-separated)', 'nas-admins'],
  ['public_url', 'sso.public_url', 'Public URL of ZettNAS (optional)', 'https://nas.example.com'],
];

export async function renderSsoPanel() {
  const host = document.getElementById('sec-sso-card');
  if (!host) return;
  let cfg;
  try {
    cfg = await api.get('/api/auth/oidc/settings');
  } catch (err) {
    host.textContent = '';
    return;
  }
  host.replaceChildren();
  const title = document.createElement('div');
  title.className = 'guard-title';
  title.textContent = t('sso.title', '🔑 Single sign-on (OpenID Connect)');
  const desc = document.createElement('div');
  desc.className = 'guard-muted';
  desc.textContent = t('sso.desc', 'Let people sign in with Authentik, Keycloak, Authelia or another OpenID Connect provider. Register ZettNAS there with this redirect URI: {uri}', { uri: cfg.redirect_uri });
  const form = document.createElement('form');
  form.className = 'sso-form';
  const enabled = document.createElement('label');
  enabled.className = 'guard-toggle';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.name = 'enabled';
  cb.checked = Boolean(cfg.enabled);
  enabled.append(cb, Object.assign(document.createElement('span'), { textContent: t('sso.enabled', 'Show the single sign-on button') }));
  form.append(enabled);
  for (const [key, i18n, label, placeholder] of FIELDS) {
    const wrap = document.createElement('label');
    wrap.className = 'sso-field';
    const span = document.createElement('span');
    span.textContent = t(i18n, label);
    const input = document.createElement('input');
    input.name = key;
    input.className = 'tz-select-input';
    input.type = key === 'client_secret' ? 'password' : 'text';
    input.autocomplete = 'off';
    input.placeholder = placeholder;
    const v = cfg[key];
    input.value = Array.isArray(v) ? v.join(', ') : v || '';
    wrap.append(span, input);
    form.append(wrap);
  }
  const save = document.createElement('button');
  save.type = 'submit';
  save.className = 'btn-pill-toggle';
  save.textContent = t('sso.save', 'Save');
  form.append(save);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = { enabled: cb.checked };
    for (const [key] of FIELDS) {
      const v = String(fd.get(key) || '').trim();
      body[key] = key === 'admin_groups' ? v.split(',').map((s) => s.trim()).filter(Boolean) : v;
    }
    try {
      await api.put('/api/auth/oidc/settings', body);
      showToast(t('sso.saved', 'Single sign-on settings saved'), 'success');
      renderSsoPanel();
    } catch (err) {
      showToast(t('sso.save_failed', 'Could not save: {error}', { error: err.message }), 'error');
    }
  });
  host.append(title, desc, form);
}

const LDAP_FIELDS = [
  ['server_url', 'ldap.server', 'Server', 'ldaps://dc.home.lan'],
  ['base_dn', 'ldap.base_dn', 'Base DN', 'dc=home,dc=lan'],
  ['bind_dn', 'ldap.bind_dn', 'Service account DN', 'cn=zettnas,ou=service,dc=home,dc=lan'],
  ['bind_password', 'ldap.bind_password', 'Service account password', ''],
  ['user_filter', 'ldap.user_filter', 'User filter', '(sAMAccountName={username})'],
  ['admin_groups', 'ldap.admin_groups', 'Admin groups (comma-separated)', 'NAS Admins'],
];

/** LDAP / Active Directory settings in Security (M6). */
export async function renderLdapPanel() {
  const host = document.getElementById('sec-ldap-card');
  if (!host) return;
  let cfg;
  try {
    cfg = await api.get('/api/auth/ldap/settings');
  } catch (err) {
    host.textContent = '';
    return;
  }
  host.replaceChildren();
  const title = Object.assign(document.createElement('div'), { className: 'guard-title', textContent: t('ldap.title', '🏢 LDAP / Active Directory') });
  const desc = Object.assign(document.createElement('div'), {
    className: 'guard-muted',
    textContent: t('ldap.desc', 'People sign in with their directory name and password. Local accounts keep their own password. Use ldaps:// or StartTLS.'),
  });
  const form = document.createElement('form');
  form.className = 'sso-form';
  const toggle = (name, label, checked) => {
    const l = document.createElement('label');
    l.className = 'guard-toggle';
    const cb = Object.assign(document.createElement('input'), { type: 'checkbox', name, checked: Boolean(checked) });
    l.append(cb, Object.assign(document.createElement('span'), { textContent: label }));
    form.append(l);
    return cb;
  };
  const enabled = toggle('enabled', t('ldap.enabled', 'Allow directory sign-in'), cfg.enabled);
  for (const [key, i18n, label, placeholder] of LDAP_FIELDS) {
    const wrap = Object.assign(document.createElement('label'), { className: 'sso-field' });
    const input = Object.assign(document.createElement('input'), {
      name: key,
      className: 'tz-select-input',
      type: key === 'bind_password' ? 'password' : 'text',
      autocomplete: 'off',
      placeholder,
      value: Array.isArray(cfg[key]) ? cfg[key].join(', ') : cfg[key] || '',
    });
    wrap.append(Object.assign(document.createElement('span'), { textContent: t(i18n, label) }), input);
    form.append(wrap);
  }
  const startTls = toggle('start_tls', t('ldap.start_tls', 'Use StartTLS (for ldap:// servers)'), cfg.start_tls);
  const row = Object.assign(document.createElement('div'), { className: 'bench-actions' });
  const save = Object.assign(document.createElement('button'), { type: 'submit', className: 'btn-pill-toggle', textContent: t('sso.save', 'Save') });
  const test = Object.assign(document.createElement('button'), { type: 'button', className: 'btn-pill-toggle', textContent: t('ldap.test', 'Test connection') });
  const status = Object.assign(document.createElement('span'), { className: 'guard-muted' });
  status.setAttribute('aria-live', 'polite');
  row.append(save, test, status);
  form.append(row);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = { enabled: enabled.checked, start_tls: startTls.checked };
    for (const [key] of LDAP_FIELDS) {
      const v = String(fd.get(key) || '').trim();
      body[key] = key === 'admin_groups' ? v.split(',').map((x) => x.trim()).filter(Boolean) : v;
    }
    try {
      await api.put('/api/auth/ldap/settings', body);
      showToast(t('ldap.saved', 'Directory settings saved'), 'success');
    } catch (err) {
      showToast(t('sso.save_failed', 'Could not save: {error}', { error: err.message }), 'error');
    }
  });
  test.addEventListener('click', async () => {
    status.textContent = '…';
    try {
      const r = await api.post('/api/auth/ldap/test', {});
      status.textContent = r.ok ? t('ldap.test_ok', 'Connected') : r.message;
    } catch (err) {
      status.textContent = err.message;
    }
  });
  host.append(title, desc, form);
}
