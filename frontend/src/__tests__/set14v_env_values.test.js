import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { openContainerInspector, switchContainerTab, _resetContainerModalForTesting } from '../components/container-modal.js';
import { api } from '../api.js';
import * as utils from '../utils.js';
import * as toast from '../toast.js';

const MASK = '••••••••';
const details = (value) => ({
  cid: 'c1',
  overview: { id: 'c1', name: 'app', state: 'running', running: true },
  resources: {},
  mounts: [],
  ports: [],
  networks: [],
  env: [{ key: 'API_KEY', value, masked_value: MASK, is_secret: true }],
});

beforeEach(() => {
  _resetContainerModalForTesting();
  vi.restoreAllMocks();
});
afterEach(() => _resetContainerModalForTesting());

async function openEnv(unmaskedValue) {
  const get = vi.spyOn(api, 'get').mockImplementation(async (url) => {
    if (url.includes('/details?unmask=true')) return details(unmaskedValue);
    if (url.includes('/details')) return details(MASK); // the server masks both fields
    return {};
  });
  await openContainerInspector('c1', 'app');
  await switchContainerTab('env');
  return get;
}

describe('the Environment tab acts on the value, not on the mask (SET-14, Apps 26)', () => {
  it('show and copy ask for the real value once', async () => {
    const get = await openEnv('real-secret');
    const copy = vi.spyOn(utils, 'copyText').mockResolvedValue(true);
    document.querySelector('.btn-toggle-secret').click();
    await vi.waitFor(() => expect(document.getElementById('env-val-0').textContent).toBe('real-secret'));
    document.querySelector('.btn-copy-env').click();
    await vi.waitFor(() => expect(copy).toHaveBeenCalledWith('real-secret'));
    expect(get.mock.calls.filter(([u]) => u.includes('unmask=true')).length).toBe(1);
  });

  it('someone who may not see it is told so, and nothing is copied', async () => {
    await openEnv(MASK);
    const copy = vi.spyOn(utils, 'copyText').mockResolvedValue(true);
    const said = vi.spyOn(toast, 'showToast');
    document.querySelector('.btn-copy-env').click();
    await vi.waitFor(() => expect(said).toHaveBeenCalledWith('Only people who manage apps can see this value.', 'warning'));
    expect(copy).not.toHaveBeenCalled();
    document.querySelector('.btn-toggle-secret').click();
    await new Promise((r) => setTimeout(r, 0));
    expect(document.getElementById('env-val-0').textContent).toBe(MASK);
  });
});
