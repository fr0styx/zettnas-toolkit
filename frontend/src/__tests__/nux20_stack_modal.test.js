/** NUX-20: the Docker stack inspector and stack picker read as plain, translatable words. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { openStackModal, openStackPickerModal, deployComposeStackSnippet, _resetStackModalForTesting } from '../components/stack-modal.js';
import { api } from '../api.js';
import { showToast, showConfirmToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const byId = (id) => document.getElementById(id);
const flush = () => new Promise((r) => setTimeout(r, 0));

const DETAILS = {
  name: 'web',
  origin: 'compose',
  config_file: '/mnt/user/appdata/web/compose.yaml',
  has_real_file: true,
  status: 'partial',
  running_count: 1,
  total_count: 2,
  compose_yaml: 'services:\n  app:\n    image: nginx\n',
  containers: [
    { id: 'c1', service: 'app', image: 'nginx', state: 'running', ports: [{ host_port: 8080, container_port: 80, proto: 'tcp' }], webui_url: 'http://x:8080' },
    { id: 'c2', name: 'db', image: 'postgres', state: 'exited', ports: [] },
  ],
};

describe('stack inspector (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    _resetStackModalForTesting();
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    _resetStackModalForTesting();
  });

  it('describes a stack loaded from its file', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(DETAILS);
    await openStackModal('web');
    expect(byId('stack-header-title').textContent).toBe('Stack: web');
    expect(byId('stack-header-status').textContent).toBe('● 1/2 Running');
    expect(byId('stack-path-label').textContent).toBe('/mnt/user/appdata/web/compose.yaml');
    expect(byId('stack-modal-msg').textContent).toBe('Loaded from the Compose file on disk');
    const services = byId('stack-services-list').textContent;
    for (const w of ['● Running', '● Stopped', 'Host network / none', 'Ports:', 'Web UI', 'Container details']) expect(services).toContain(w);
    const win = byId('stack-inspector-window').textContent;
    for (const w of ['Compose file (compose.yaml)', 'Environment (.env)', 'Services', 'Copy YAML', 'Save and redeploy', 'Redeploy']) expect(win).toContain(w);
  });

  it('says where a stack without a file came from, or that it could not load', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ name: 'live', location_type: 'synthesized', has_real_file: false, running_count: 0, total_count: 0, containers: [] });
    await openStackModal('live');
    expect(byId('stack-path-label').textContent).toBe('Rebuilt from the running containers');
    expect(byId('stack-modal-msg').textContent).toBe('Rebuilt from the running containers');
    expect(byId('stack-services-list').textContent).toBe('No containers found for this stack.');

    get.mockResolvedValue({ name: 'plain', running_count: 0, total_count: 1 });
    await openStackModal('plain');
    expect(byId('stack-path-label').textContent).toBe('Docker Compose project');

    get.mockRejectedValue(new Error('no daemon'));
    await openStackModal('gone');
    expect(byId('stack-modal-msg').textContent).toBe('Could not load the stack: no daemon');
  });

  it('warns about an AI-written stack and asks before deploying it with host access', async () => {
    deployComposeStackSnippet('services:\n  app:\n    image: nginx\n');
    await flush();
    expect(byId('stack-header-title').textContent).toBe('Deploy stack: app');
    expect(byId('stack-header-origin').textContent).toBe('AI template');
    expect(byId('stack-modal-msg').textContent).toBe('Loaded an AI-written Compose file. Review it, then click “Save and redeploy”.');

    deployComposeStackSnippet('services:\n  tool:\n    image: x\n    privileged: true\n');
    await flush();
    expect(byId('stack-modal-msg').textContent).toMatch(/^Review before deploying\. This AI-written stack asks for host access:\n/);
    byId('stack-save-btn').click();
    await flush();
    const [title, msg, , no] = showConfirmToast.mock.calls.at(-1);
    expect(title).toBe('Deploy a stack with host access?');
    expect(msg).toMatch(/^This Compose file came from an AI answer and asks for:\n/);
    no();
  });

  it('reports a failed save', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(DETAILS);
    await openStackModal('web');
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: false, error: 'bad yaml' });
    byId('stack-save-btn').click();
    await flush();
    expect(byId('stack-modal-msg').textContent).toBe('Error: bad yaml');
    expect(showToast).toHaveBeenLastCalledWith('bad yaml', 'error');
    post.mockResolvedValue({ success: false });
    byId('stack-save-btn').click();
    await flush();
    expect(showToast).toHaveBeenLastCalledWith('Could not save the stack', 'error');
    post.mockRejectedValue(new Error('timeout'));
    byId('stack-save-btn').click();
    await flush();
    expect(byId('stack-modal-msg').textContent).toBe('Error: timeout');
  });

  it('shows what a start, stop or restart did', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(DETAILS);
    await openStackModal('web');
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: false, error: 'busy' });
    byId('stack-action-restart').click();
    expect(byId('stack-modal-msg').textContent).toBe('Running “restart”…');
    await flush();
    expect(byId('stack-modal-msg').textContent).toBe('“restart” failed: busy');
    post.mockResolvedValue({ success: false });
    byId('stack-action-stop').click();
    await flush();
    expect(showToast).toHaveBeenLastCalledWith('“stop” failed', 'error');
    post.mockRejectedValue(new Error('down'));
    byId('stack-action-start').click();
    await flush();
    expect(byId('stack-modal-msg').textContent).toBe('“start” failed: down');
    post.mockResolvedValue({ success: true });
    byId('stack-action-redeploy').click();
    await flush();
    await flush();
    expect(showToast).toHaveBeenCalledWith("Stack action 'redeploy' completed!", 'success');
    expect(byId('stack-modal-msg').textContent).toBe('Loaded from the Compose file on disk');
  });
});

describe('stack picker (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    _resetStackModalForTesting();
  });

  it('counts stacks and shows each one’s state', async () => {
    await openStackPickerModal([
      { name: 'all', running_count: 2, total_count: 2, working_dir: '/w/all', services: ['a', 'b', 'c', 'd', 'e', 'f', 'g'] },
      { name: 'none', running_count: 0, total_count: 3, services: [] },
      { name: 'some', running_count: 1, total_count: 3, config_files: '/w/some.yaml', services: ['x'] },
    ]);
    const overlay = byId('stack-picker-overlay');
    expect(overlay.querySelector('#stack-picker-badge').textContent).toBe('3 Stacks');
    const cards = overlay.querySelectorAll('.stack-picker-card');
    expect(cards[0].textContent).toContain('2/2 Running');
    expect(cards[0].textContent).toContain('+1 more');
    expect(cards[0].textContent).toContain('Services:');
    expect(cards[1].textContent).toContain('Stopped (3)');
    expect(cards[1].textContent).toContain('Managed by Docker');
    expect(cards[2].textContent).toContain('1/3 Running');
    expect(overlay.textContent).toContain('Click a stack to open it');

    await openStackPickerModal([{ name: 'one', running_count: 0, total_count: 0 }]);
    expect(overlay.querySelector('#stack-picker-badge').textContent).toBe('1 Stack');
    const search = overlay.querySelector('#stack-picker-search');
    search.value = 'zzz';
    search.oninput();
    expect(byId('stack-picker-list').textContent.trim()).toBe('No Compose stacks match "zzz"');
  });
});
