/** NUX-20: the install window's name and port checks, a failed install, the template check and load errors. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { api } from '../api.js';
import { DockManager } from '../components/dock.js';
import { openAppDeployModal, openSideloadAppModal, openAppSourcesModal, fetchAndRenderDockerContainers } from '../components/management.js';

const wait = (ms = 320) => new Promise((r) => setTimeout(r, ms));
let answers;

function routes(extra = {}) {
  answers = {
    resolve: { app_id: 'uptime-kuma', default_port: 3001, suggested_port: 3001, conflict_detected: false },
    name: { exists: false },
    port: { available: true },
    ...extra,
  };
  vi.spyOn(api, 'get').mockImplementation(async (url) => {
    if (url.includes('/resolve')) return answers.resolve;
    if (url.includes('check_container_name')) return answers.name;
    if (url.includes('check_port')) return answers.port;
    return { apps: [{ id: 'uptime-kuma', name: 'Uptime Kuma', default_port: 3001 }] };
  });
  vi.spyOn(api, 'request').mockResolvedValue({ ok: true, status: 200, json: async () => ({ default_port: 3001, compose_yaml: 'x: 1' }) });
}

describe('install window checks (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="os-dock-container"><div id="os-dock"></div></div>';
  });
  afterEach(() => {
    const modal = document.getElementById('app-deploy-modal-overlay');
    if (modal && modal._close) modal._close();
    vi.restoreAllMocks();
  });

  it('says what is wrong with a name or a port, and when all is ready', async () => {
    routes();
    await openAppDeployModal('uptime-kuma');
    const banner = document.getElementById('adm-conflict-banner');
    const name = document.getElementById('adm-name-input');
    const port = document.getElementById('adm-port-input');

    name.value = '';
    name.oninput();
    await wait();
    expect(banner.textContent).toContain('Invalid name: The container needs a name.');

    answers.name = { exists: true, name: 'kuma' };
    name.value = 'kuma';
    name.oninput();
    await wait();
    expect(banner.textContent).toContain('Name in use: A container named kuma already exists.');

    answers.name = { exists: false };
    port.value = '0';
    port.oninput();
    await wait();
    expect(banner.textContent).toContain('Invalid port: Enter a port from 1 to 65535.');

    answers.port = { available: false, in_use_by: 'grafana' };
    port.value = '3001';
    port.oninput();
    await wait();
    expect(banner.textContent).toContain('Port in use: Port 3001 is already in use by grafana.');

    answers.port = { available: true };
    port.oninput();
    await wait();
    expect(banner.textContent).toContain('Ready to install: Port 3001 is free for the container kuma.');
  });

  it('offers to install alongside an existing copy, or to replace it', async () => {
    routes({
      resolve: {
        app_id: 'uptime-kuma', default_port: 3001, suggested_port: 3002, conflict_detected: false,
        existing_container: { name: 'uptime-kuma', state: 'running' }, suggested_container_name: 'uptime-kuma-2',
      },
    });
    await openAppDeployModal('uptime-kuma');
    const banner = document.getElementById('adm-conflict-banner');
    expect(banner.textContent).toContain('Install alongside:');

    document.getElementById('adm-choice-replace-btn').click();
    await wait(50);
    expect(banner.textContent).toContain('Stop & replace:');

    const name = document.getElementById('adm-name-input');
    answers.name = { exists: true, name: name.value };
    name.oninput();
    await wait();
    expect(banner.textContent).toContain(`The container ${name.value} is stopped and replaced.`);

    answers.port = { available: false, in_use_by: `container '${name.value}'` };
    const port = document.getElementById('adm-port-input');
    port.value = '3001';
    port.oninput();
    await wait();
    expect(banner.textContent).toContain('is used by');
  });

  it('stops an install whose name or port was taken meanwhile, and reports a lost install', async () => {
    routes();
    await openAppDeployModal('uptime-kuma');
    const banner = document.getElementById('adm-conflict-banner');
    const deploy = document.getElementById('adm-deploy-confirm-btn');

    answers.name = { exists: true, name: 'uptime-kuma' };
    await deploy.onclick();
    expect(banner.textContent).toContain('Name in use:');

    answers.name = { exists: false };
    answers.port = { available: false, in_use_by: 'grafana' };
    await deploy.onclick();
    expect(banner.textContent).toContain('Port in use: Port 3001 is already in use by grafana.');

    answers.port = { available: true };
    api.request.mockRejectedValue(new Error(''));
    await deploy.onclick();
    await wait(50);
    expect(DockManager.windows['app-deploy'].title).toBe('❌ UPTIME-KUMA failed to install');
  });
});

describe('template checks and load errors (NUX-20)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('checks a sideloaded template and says when the check failed', async () => {
    document.body.innerHTML = `
      <div id="modal-sideload-app">
        <button id="sideload-tab-url"></button><button id="sideload-tab-paste"></button>
        <div id="sideload-input-url-wrap"><input id="sideload-url-input" value="https://example.com/app.yml"></div>
        <div id="sideload-input-paste-wrap"><textarea id="sideload-content-input"></textarea></div>
        <button id="btn-sideload-inspect"></button><div id="sideload-inspect-result"></div><button id="btn-sideload-confirm"></button>
      </div>`;
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', app: { name: 'Demo', image: 'demo:1', type: 'standalone', default_port: 8080 }, security_rating: 'safe', security_flags: [] });
    openSideloadAppModal();
    const inspect = document.getElementById('btn-sideload-inspect');
    await inspect.onclick();
    const result = document.getElementById('sideload-inspect-result');
    expect(result.textContent).toContain('No high-privilege risks found');
    expect(result.textContent).toContain('Image: demo:1');
    expect(result.textContent).toContain('Default port: 8080');
    expect(inspect.textContent).toContain('Check the template');

    post.mockRejectedValue(new Error('bad yaml'));
    await inspect.onclick();
    expect(result.textContent).toBe('Check failed: bad yaml');
  });

  it('says when a template source could not be added', async () => {
    document.body.innerHTML = '';
    vi.spyOn(api, 'get').mockResolvedValue([]);
    vi.spyOn(api, 'post').mockRejectedValue(new Error('not JSON'));
    await openAppSourcesModal();
    document.getElementById('asm-input-name').value = 'Mine';
    document.getElementById('asm-input-url').value = 'https://example.com/t.json';
    await document.getElementById('asm-btn-add-custom').onclick();
    expect(document.getElementById('asm-form-status').textContent).toBe('Error: not JSON');
  });

  it('says when the containers could not be loaded', async () => {
    document.body.innerHTML = '<div id="mgmt-pane-docker"><table><tbody id="docker-containers-tbody"></tbody></table></div>';
    vi.spyOn(api, 'get').mockRejectedValue(new Error('socket gone'));
    await fetchAndRenderDockerContainers();
    expect(document.getElementById('docker-containers-tbody').textContent).toBe('Could not load the containers: socket gone');
  });
});
