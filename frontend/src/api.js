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

async function request(endpoint, options = {}) {
  const url = endpoint;
  const config = { ...options };
  config.headers = { ...options.headers };

  const token = auth.getToken();
  if (token && !config.headers['Authorization']) {
    config.headers['Authorization'] = `Bearer ${token}`;
  }

  if (config.body && typeof config.body === 'object' && !(config.body instanceof FormData)) {
    if (!config.headers['Content-Type']) {
      config.headers['Content-Type'] = 'application/json';
    }
    config.body = JSON.stringify(config.body);
  }

  try {
    const res = await window.fetch(url, config);

    if (res.status === 401) {
      ZettEventBus.emit('auth:required', { url });
      const overlay = document.getElementById('login-overlay');
      if (overlay) overlay.style.display = 'flex';
      const dock = document.getElementById('os-dock-container');
      if (dock) dock.style.display = 'none';
      throw new Error('Unauthorized');
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
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    return res.json();
  },
  async post(url, body = {}, options = {}) {
    const res = await request(url, { method: 'POST', body, ...options });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    return res.json();
  },
  async delete(url, options = {}) {
    const res = await request(url, { method: 'DELETE', ...options });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    return res.json();
  }
};

// Global fetch interceptor ensuring any standard fetch calls attach authorization headers
const _originalFetch = window.fetch;
window.fetch = async function(resource, config = {}) {
  const token = auth.getToken();
  if (token) {
    if (!config.headers) config.headers = {};
    if (config.headers instanceof Headers) {
      if (!config.headers.has('Authorization')) {
        config.headers.set('Authorization', 'Bearer ' + token);
      }
    } else if (typeof config.headers === 'object') {
      if (!config.headers['Authorization']) {
        config.headers['Authorization'] = 'Bearer ' + token;
      }
    }
  }

  const res = await _originalFetch(resource, config);
  if (res.status === 401) {
    ZettEventBus.emit('auth:required', { resource });
    const overlay = document.getElementById('login-overlay');
    if (overlay) overlay.style.display = 'flex';
    const dock = document.getElementById('os-dock-container');
    if (dock) dock.style.display = 'none';
  }
  return res;
};

export default api;
