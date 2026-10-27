import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() }, auth: { setToken: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const wiz = await import('../components/setup-wizard.js');

const MARKUP = `
  <div id="setup-wizard-modal"><div class="smart-modal-window"><div class="smart-modal-body">
    <div data-setup-step="1">welcome</div>
    <div data-setup-step="1"><input id="setup-server-name"></div>
    <div data-setup-step="2"><input id="setup-current-pwd"><input id="setup-new-pwd"><input id="setup-confirm-pwd"><div id="setup-wizard-err"></div></div>
    <div data-setup-step="3"><div id="setup-storage-info"></div></div>
    <div data-setup-step="4"><div id="setup-share-host" hidden></div><div id="setup-share-form"><input type="checkbox" id="setup-share-create" checked><input id="setup-share-name" value="Family"></div></div>
    <div data-setup-step="5"><input id="setup-person-name"><input id="setup-person-pwd"><select id="setup-person-role"><option value="kid">kid</option></select></div>
    <div data-setup-step="6"><select id="setup-timezone"></select></div>
    <div><button id="setup-wizard-submit"></button></div>
  </div></div></div>`;

const visibleStep = () => [...document.querySelectorAll('[data-setup-step]')].filter((b) => !b.hidden).map((b) => b.dataset.setupStep);
const fill = (id, v) => { document.getElementById(id).value = v; };

describe('six-step setup (UX-17)', () => {
  beforeEach(() => {
    document.body.innerHTML = MARKUP;
    vi.clearAllMocks();
    api.get.mockImplementation(async (url) => (url.includes('platform') ? { platform: 'generic_linux', capabilities: { is_observer_mode: false } } : { pools: [{ name: 'tank' }] }));
  });

  it('walks name, password, storage, share, people, time zone', async () => {
    const stepper = wiz.initWizardStepper(document.getElementById('setup-wizard-modal'));
    expect(document.querySelectorAll('.setup-steps li').length).toBe(6);
    expect(visibleStep()).toEqual(['1', '1']);
    const next = document.getElementById('setup-wizard-next');
    next.click();
    expect(stepper.current).toBe(2);
    next.click(); // empty password: stays
    expect(stepper.current).toBe(2);
    fill('setup-current-pwd', 'admin'); fill('setup-new-pwd', 'a-long-password'); fill('setup-confirm-pwd', 'a-long-password');
    next.click();
    expect(stepper.current).toBe(3);
    await new Promise((r) => setTimeout(r, 0));
    expect(document.getElementById('setup-storage-info').textContent).toContain('tank');
    next.click(); next.click();
    expect(stepper.current).toBe(5);
    fill('setup-person-name', 'mia'); fill('setup-person-pwd', 'short');
    next.click(); // a person needs a real password
    expect(stepper.current).toBe(5);
    expect(document.getElementById('setup-wizard-err').textContent).toContain('8');
    fill('setup-person-pwd', 'long-enough-1');
    next.click();
    expect(stepper.current).toBe(6);
    expect(document.getElementById('setup-wizard-submit').hidden).toBe(false);
  });

  it('on host-managed storage the share step points to the host', async () => {
    api.get.mockImplementation(async (url) => (url.includes('platform') ? { platform: 'unraid', capabilities: { is_observer_mode: true } } : { pools: [] }));
    const res = await wiz.loadStorageStep();
    expect(res.observer).toBe(true);
    expect(document.getElementById('setup-share-form').hidden).toBe(true);
    expect(document.getElementById('setup-share-host').textContent).toContain('Unraid');
    expect(document.getElementById('setup-storage-info').textContent).toContain('Unraid');
    api.get.mockRejectedValue(new Error('down'));
    expect((await wiz.loadStorageStep()).observer).toBe(false);
  });

  it('saves the name, time zone, share and person, and says what failed', async () => {
    fill('setup-server-name', 'Home');
    wiz.fillTimezones(document.getElementById('setup-timezone'), 'Europe/Berlin');
    expect(document.getElementById('setup-timezone').value).toBe('Europe/Berlin');
    fill('setup-person-name', 'mia'); fill('setup-person-pwd', 'long-enough-1');
    api.put.mockResolvedValue({ server_name: 'Home', timezone: 'Europe/Berlin' });
    api.post.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('taken'));
    await wiz.saveSetupExtras();
    expect(api.put).toHaveBeenCalledWith('/api/system/identity', { server_name: 'Home', timezone: 'Europe/Berlin' });
    expect(api.post).toHaveBeenCalledWith('/api/storage/shares', { name: 'Family', security: 'private' });
    expect(api.post).toHaveBeenCalledWith('/api/users', { username: 'mia', password: 'long-enough-1', role_id: 'kid' });
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('taken'), 'warning');
    expect(document.title).toBe('Home · ZettNAS');
  });

  it('a failed name save or share is reported, the rest carries on', async () => {
    fill('setup-server-name', 'Home');
    api.put.mockRejectedValue(new Error('nope'));
    api.post.mockRejectedValue(new Error('observer'));
    await wiz.saveSetupExtras();
    expect(showToast).toHaveBeenCalledTimes(2);
    wiz.applyServerName('');
    expect(document.title).toBe('ZettNAS');
  });
});
