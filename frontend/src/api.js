/**
 * ZettNAS Toolkit Centralized API Client
 * Handles session tokens, HTTP requests, 401 handling, and response parsing.
 */
import { ZettEventBus } from './event-bus.js';

const TOKEN_KEY = 'zettnas_token';

export const auth = {
  getToken: () => localStorage.getItem(TOKEN_KEY),
  setToken: (token) => localStorage.setItem(TOKEN_KEY, token),
  clearToken: () => localStorage.removeItem(TOKEN_KEY),
  hasToken: () => !!localStorage.getItem(TOKEN_KEY)
};

// The on-device LCD renderer (headless Chromium) authenticates with an
// internal token passed as ?lcd_token=. Adopt it before any request is made
// and remove it from the visible URL.
(() => {
  try {
    const params = new URLSearchParams(window.location.search);
    const lcdToken = params.get('lcd_token');
    if (lcdToken) {
      auth.setToken(lcdToken);
      params.delete('lcd_token');
      const qs = params.toString();
      history.replaceState(null, '', window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash);
    }
  } catch (e) { /* non-browser context */ }
})();

/**
 * Error thrown for non-2xx responses. The backend answers with
 * {error, detail, code}; `message` is the human-readable `detail`.
 */
export class ApiError extends Error {
  constructor(message, { status = 0, error = 'error', body = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.error = error;
    this.body = body;
  }

  static async from(res) {
    let body = null;
    try { body = await res.json(); } catch (e) { /* non-JSON body */ }
    const detail = (body && typeof body.detail === 'string' && body.detail.trim())
      ? body.detail.trim()
      : (res.statusText ? `HTTP ${res.status}: ${res.statusText}` : `Request failed (HTTP ${res.status})`);
    return new ApiError(detail, { status: res.status, error: (body && body.error) || 'error', body });
  }
}

// Destructive-action standard: the server answers 428 "confirmation_required" until the
// request carries a single-use X-Confirm-Token. Callers that already asked the user pass
// { confirmed: true }; otherwise the registered handler (the app's confirm dialog) asks first.
let _confirmationHandler = null;

export function setConfirmationHandler(fn) {
  _confirmationHandler = typeof fn === 'function' ? fn : null;
}

async function _askToConfirm(info) {
  if (_confirmationHandler) return Boolean(await _confirmationHandler(info));
  if (typeof window !== 'undefined' && typeof window.confirm === 'function') {
    return window.confirm(`${info.summary || 'This action cannot be undone'}?`);
  }
  return false;
}

async function request(endpoint, options = {}) {
  const url = endpoint;
  const config = { ...options };
  delete config.confirmed;
  delete config._confirmRetry;
  config.headers = { ...options.headers };

  const token = auth.getToken();
  if (token && !config.headers['Authorization']) {
    config.headers['Authorization'] = `Bearer ${token}`;
  }

  const isBinary = (typeof FormData !== 'undefined' && config.body instanceof FormData) ||
    (typeof Blob !== 'undefined' && config.body instanceof Blob);
  if (config.body && typeof config.body === 'object' && !isBinary) {
    if (!config.headers['Content-Type']) {
      config.headers['Content-Type'] = 'application/json';
    }
    config.body = JSON.stringify(config.body);
  }

  try {
    const res = await window.fetch(url, config);

    if (res.status === 401) {
      const isLcd = typeof window !== 'undefined' && (
        window.location.search.includes('mode=lcd') ||
        (typeof document !== 'undefined' && document.body && document.body.classList.contains('lcd-direct'))
      );
      if (!isLcd) {
        auth.clearToken();
        document.documentElement.classList.remove('has-auth-session');
        document.documentElement.classList.add('auth-required');
        ZettEventBus.emit('auth:required', { url });
        const overlay = document.getElementById('login-overlay');
        if (overlay) {
          overlay.style.removeProperty('opacity');
          overlay.style.display = 'flex';
        }
        const dock = document.getElementById('os-dock-container');
        if (dock) dock.style.display = 'none';
      }
      throw new ApiError('Unauthorized', { status: 401, error: 'unauthorized' });
    }

    if (res.status === 428 && !options._confirmRetry) {
      let info = null;
      try {
        info = await res.clone().json();
      } catch (e) {
        info = null;
      }
      if (info && info.error === 'confirmation_required') {
        const ok = options.confirmed === true || (await _askToConfirm(info));
        if (!ok) throw new ApiError('Cancelled', { status: 428, error: 'cancelled' });
        const tokenRes = await window.fetch('/api/confirmations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({ action: info.action, target: info.target || '' }),
        });
        if (!tokenRes.ok) throw await ApiError.from(tokenRes);
        const { token: confirmToken } = await tokenRes.json();
        return request(endpoint, {
          ...options,
          _confirmRetry: true,
          headers: { ...options.headers, 'X-Confirm-Token': confirmToken },
        });
      }
    }

    return res;
  } catch (err) {
    throw err;
  }
}

export const api = {
  request,
  async get(url, options = {}) {
    const res = await request(url, { method: 'GET', ...options });
    if (!res.ok) throw await ApiError.from(res);
    return res.json();
  },
  async post(url, body = {}, options = {}) {
    const res = await request(url, { method: 'POST', body, ...options });
    if (!res.ok) throw await ApiError.from(res);
    return res.json();
  },
  async put(url, body = {}, options = {}) {
    const res = await request(url, { method: 'PUT', body, ...options });
    if (!res.ok) throw await ApiError.from(res);
    return res.json();
  },
  async patch(url, body = {}, options = {}) {
    const res = await request(url, { method: 'PATCH', body, ...options });
    if (!res.ok) throw await ApiError.from(res);
    return res.json();
  },
  async delete(url, options = {}) {
    const res = await request(url, { method: 'DELETE', ...options });
    if (!res.ok) throw await ApiError.from(res);
    return res.json();
  },
  async downloadBlob(url, defaultFilename = 'download.zip', options = {}) {
    const fetchOptions = { method: options.method || 'GET', ...options };
    const res = await request(url, fetchOptions);
    if (!res.ok) throw await ApiError.from(res);
    const blob = await res.blob();
    const disposition = res.headers.get('content-disposition') || '';
    let filename = defaultFilename;
    const match = disposition.match(/filename="?([^";]+)"?/);
    if (match && match[1]) {
      filename = match[1];
    }
    const blobUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(blobUrl);
    return filename;
  }
};

export { request, request as apiFetch };
export default api;

