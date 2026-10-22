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
