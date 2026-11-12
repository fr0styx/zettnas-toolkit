/** SET-03: the Security and Notifications tabs load an administrator's set-up for administrators only. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadAccountPane, loadSecurityPane, loadNotificationsPane } from '../components/management/admin-panes.js';
import '../route-access.js';
import { ZettEventBus } from '../event-bus.js';
import { fetchAndRenderSecurityPosture } from '../components/management/security.js';
import { fetchAndRenderNotificationConfig } from '../components/management/notifications.js';
import { renderApiTokens } from '../components/settings.js';
import { renderGuardPanel } from '../components/guard-panel.js';
import { renderFileActivity } from '../components/file-activity.js';
import { renderSsoPanel, renderLdapPanel } from '../components/sso.js';
import { installMyData } from '../components/management/user-data.js';
import { renderPushCard } from '../components/push-card.js';

vi.mock('../components/management/security.js', () => ({ fetchAndRenderSecurityPosture: vi.fn() }));
vi.mock('../components/management/notifications.js', () => ({ fetchAndRenderNotificationConfig: vi.fn() }));
vi.mock('../components/settings.js', () => ({ renderApiTokens: vi.fn() }));
vi.mock('../components/guard-panel.js', () => ({ renderGuardPanel: vi.fn() }));
vi.mock('../components/file-activity.js', () => ({ renderFileActivity: vi.fn() }));
vi.mock('../components/sso.js', () => ({ renderSsoPanel: vi.fn(), renderLdapPanel: vi.fn() }));
vi.mock('../components/management/user-data.js', () => ({ installMyData: vi.fn() }));
vi.mock('../components/users.js', () => ({ loadAccountParts: vi.fn() }));
vi.mock('../components/push-card.js', () => ({ renderPushCard: vi.fn() }));

const flush = () => new Promise((r) => setTimeout(r, 0));
const ADMIN_LOADERS = [fetchAndRenderSecurityPosture, renderGuardPanel, renderFileActivity, renderSsoPanel, renderLdapPanel];

describe('the Security and Notifications tabs (SET-03)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <div id="mgmt-pane-security"><div id="advisor" data-admin-only></div><div id="my-data"></div></div>
      <div id="mgmt-pane-notifications"><div id="channels" data-admin-only></div><div id="push"></div></div>
      <div id="mgmt-pane-account"><div id="api" data-admin-only></div><div id="pwd"></div></div>`;
  });

  it('a family member gets their own things and nothing of the set-up', async () => {
    ZettEventBus.emit('session:user', { scopes: ['shares:read', 'shares:user_write', 'system:view'] });
    expect(loadSecurityPane()).toBe(false);
    expect(loadNotificationsPane()).toBe(false);
    await flush();
    for (const loader of [...ADMIN_LOADERS, fetchAndRenderNotificationConfig]) expect(loader).not.toHaveBeenCalled();
    expect(installMyData).not.toHaveBeenCalled(); // your data moved to My account (SET-19)
    expect(renderPushCard).toHaveBeenCalledTimes(1);
    expect(document.getElementById('advisor').hidden).toBe(true);
    expect(document.getElementById('channels').hidden).toBe(true);
    expect(document.getElementById('push').hidden).toBe(false);
  });

  it('an administrator gets both', async () => {
    ZettEventBus.emit('session:user', { scopes: ['*'] });
    expect(loadSecurityPane()).toBe(true);
    expect(loadNotificationsPane()).toBe(true);
    await flush();
    for (const loader of [...ADMIN_LOADERS, fetchAndRenderNotificationConfig]) expect(loader).toHaveBeenCalledTimes(1);
    expect(renderApiTokens).not.toHaveBeenCalled(); // API keys moved to My account (SET-19)
    expect(renderPushCard).toHaveBeenCalledTimes(1);
    expect(document.getElementById('advisor').hidden).toBe(false);
  });
});

describe('My account (SET-19, decision X4)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="mgmt-pane-account"><div id="api" data-admin-only></div><div id="pwd"></div></div>';
  });

  it('every role gets their own sign-in things and data; only an administrator the API keys', async () => {
    const { loadAccountParts } = await import('../components/users.js');
    ZettEventBus.emit('session:user', { scopes: ['shares:read', 'system:view'] });
    expect(loadAccountPane()).toBe(false);
    await flush();
    expect(loadAccountParts).toHaveBeenCalledTimes(1);
    expect(installMyData).toHaveBeenCalledTimes(1);
    expect(renderApiTokens).not.toHaveBeenCalled();
    expect(document.getElementById('api').hidden).toBe(true);
    expect(document.getElementById('pwd').hidden).toBe(false);
    vi.clearAllMocks();
    ZettEventBus.emit('session:user', { scopes: ['*'] });
    expect(loadAccountPane()).toBe(true);
    await flush();
    expect(renderApiTokens).toHaveBeenCalledTimes(1);
  });
});
