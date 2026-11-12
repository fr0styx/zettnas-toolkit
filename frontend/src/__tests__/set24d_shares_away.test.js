/** SET-24: Shared folders leads to Away from home. */
import { describe, it, expect, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const html = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');

describe('Shared folders: Away from home', () => {
  it('the shares page links to Away from home, a route the router knows', () => {
    const pane = html.slice(html.indexOf('id="mgmt-pane-storage-shares"'), html.indexOf('id="mgmt-pane-storage-remotes"'));
    expect(pane).toContain('id="btn-shares-away" href="#/away"');
    const router = fs.readFileSync(path.resolve(__dirname, '../router.js'), 'utf8');
    expect(router).toContain("away: 'pane-network-wireguard'");
  });

  it('People links to family access from anywhere through #/sharing', async () => {
    const pane = html.slice(html.indexOf('id="mgmt-pane-users"'), html.indexOf('id="mgmt-pane-notifications"'));
    expect(pane).toContain('id="btn-users-away" href="#/sharing"');
    const { ROUTES } = await import('../router.js');
    window.openManagementSection = vi.fn();
    ROUTES.sharing();
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-network-wireguard');
    delete window.openManagementSection;
  });
});
