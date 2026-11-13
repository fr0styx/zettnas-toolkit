/** SET-16: "Needs Tailscale" comes with a button that opens Network → Remote access. */
import { describe, it, expect, vi } from 'vitest';
import { installNeedsTailscale, needsTailscaleHtml, openRemoteAccess } from '../components/management/needs-tailscale.js';
import { escapeHtml } from '../utils.js';

describe('needs Tailscale', () => {
  it('says so with a button that opens Remote access', () => {
    const open = vi.fn();
    window.openManagementWindow = open;
    document.body.innerHTML = needsTailscaleHtml(escapeHtml);
    expect(document.body.textContent).toContain('Needs Tailscale.');
    installNeedsTailscale();
    installNeedsTailscale(); // once is enough
    document.querySelector('[data-open-remote-access]').click();
    expect(open).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith('mgmt-sec-away', 'mgmt-pane-network-wireguard');
    document.body.click(); // a click elsewhere opens nothing
    expect(open).toHaveBeenCalledTimes(1);
  });

  it('does nothing when Mission Control is not loaded', () => {
    delete window.openManagementWindow;
    expect(() => openRemoteAccess()).not.toThrow();
  });

  it('the cards that need Tailscale use it, and the page is called Away from home', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    for (const f of ['public-apps', 'family-access', 'fleet']) {
      expect(readFileSync(resolve(__dirname, `../components/management/${f}.js`), 'utf8')).toContain('needsTailscaleHtml(');
    }
    const html = readFileSync(resolve(__dirname, '../windows/management-window.html'), 'utf8');
    expect(html).toContain('data-mgmt-target="mgmt-sec-away" data-mgmt-pane="mgmt-pane-network-wireguard" data-route="away" title="Away from home"'); // its own page (SET-24)
    expect(html).not.toContain('network-canary-overlay');
    expect(html).not.toContain('value="macvlan"');
  });
});
