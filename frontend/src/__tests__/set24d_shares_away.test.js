/** SET-24: Shared folders leads to Away from home. */
import { describe, it, expect } from 'vitest';
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
});
