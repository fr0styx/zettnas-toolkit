/**
 * ZettNAS Toolkit Authentication Component
 * Handles login modal interactions, credential validation, and token persistence.
 */
import { auth } from '../api.js';
import { ZettEventBus } from '../event-bus.js';

export function initAuth() {
  const loginBtn = document.getElementById('login-btn');
  const loginPwd = document.getElementById('login-password');
  const overlay = document.getElementById('login-overlay');
  const dock = document.getElementById('os-dock-container');

  ZettEventBus.on('auth:required', () => {
    if (overlay) overlay.style.display = 'flex';
    if (dock) dock.style.display = 'none';
  });

  if (loginBtn && loginPwd) {
    const doLogin = async () => {
      loginBtn.textContent = 'AUTHENTICATING...';
      try {
        const res = await window.fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: loginPwd.value }),
          credentials: 'include'
        });
        if (res.ok) {
          const data = await res.json();
          if (data.token) auth.setToken(data.token);
          if (overlay) overlay.style.display = 'none';
          loginBtn.textContent = 'SECURE LOGIN';
          loginPwd.value = '';
          window.location.reload();
        } else {
          loginBtn.textContent = 'INVALID PASSWORD';
          loginBtn.style.borderColor = 'var(--crit)';
          setTimeout(() => {
            loginBtn.textContent = 'SECURE LOGIN';
            loginBtn.style.borderColor = '';
          }, 2000);
        }
      } catch (e) {
        loginBtn.textContent = 'ERROR';
      }
    };

    loginBtn.addEventListener('click', doLogin);
    loginPwd.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') doLogin();
    });
  }
}
