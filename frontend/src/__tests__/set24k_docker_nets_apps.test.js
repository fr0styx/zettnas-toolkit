import { describe, it, expect, vi, beforeEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const fetchTopo = vi.fn();
const openCreate = vi.fn();
const ensureDom = vi.fn(() => Promise.resolve());
vi.mock('../components/management/network.js', () => ({ fetchAndRenderNetworkTopology: fetchTopo, openDockerNetworkCreateModal: openCreate }));
vi.mock('../management-dom.js', () => ({ ensureManagementDom: ensureDom }));

const { appsDockerNetsHtml, installAppsDockerNets } = await import('../components/apps-docker-nets.js');
const html = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');
const cm = fs.readFileSync(path.resolve(__dirname, '../components/containers-manager.js'), 'utf8');

describe('SET-24 k: Docker networks live in the Apps window, folded for experts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `<div id="win">${appsDockerNetsHtml()}</div>`;
  });

  it('Network has no Docker tab any more', () => {
    expect(html).not.toContain('data-tab-target="mgmt-pane-network-docker"');
    expect(html).not.toContain('id="mgmt-pane-network-docker"');
    expect(html).not.toContain('id="network-docker-container"');
  });

  it('the Apps window carries the group under its installed apps, hidden with the catalog', () => {
    expect(cm).toContain('${appsDockerNetsHtml()}');
    expect(cm).toContain('installAppsDockerNets(containersWindow)');
    expect(cm).toMatch(/apps-docker-nets'\)\?\.toggleAttribute\('hidden', _cwInCatalogView\)/);
  });

  it('starts closed with the list and the create button inside', () => {
    const group = document.getElementById('apps-docker-nets');
    expect(group?.tagName).toBe('DETAILS');
    expect(group?.hasAttribute('open')).toBe(false);
    expect(group?.querySelector('summary')?.textContent).toBe('For experts: Docker networks');
    expect(group?.querySelector('#network-docker-container')).not.toBeNull();
  });

  it('opening reads the networks after Settings\' markup is in; closing reads nothing', async () => {
    const root = /** @type {HTMLElement} */ (document.getElementById('win'));
    expect(installAppsDockerNets(root)).toBe(true);
    expect(installAppsDockerNets(root)).toBe(false); // bound once
    const group = /** @type {HTMLDetailsElement} */ (document.getElementById('apps-docker-nets'));
    group.open = true;
    await vi.waitFor(() => expect(fetchTopo).toHaveBeenCalledTimes(1));
    expect(ensureDom).toHaveBeenCalled();
    group.open = false;
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchTopo).toHaveBeenCalledTimes(1);
  });

  it('the create button opens the dialog once, and network.js will not bind it again', async () => {
    installAppsDockerNets(/** @type {HTMLElement} */ (document.getElementById('win')));
    const btn = /** @type {HTMLButtonElement} */ (document.getElementById('btn-create-docker-net'));
    expect(btn.dataset.bound).toBe('1');
    btn.click();
    await vi.waitFor(() => expect(openCreate).toHaveBeenCalledTimes(1));
  });

  it('a window without the group is left alone', () => {
    document.body.innerHTML = '<div id="win"></div>';
    expect(installAppsDockerNets(/** @type {HTMLElement} */ (document.getElementById('win')))).toBe(false);
  });
});
