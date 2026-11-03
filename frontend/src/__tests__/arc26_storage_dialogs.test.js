/** ARC-26 / NUX-20: destroying and ejecting pools, removing shares: asked and reported in the reader's language. */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));
const { api } = await import('../api.js');
const { showToast, showConfirmToast } = await import('../toast.js');
const { setLanguage } = await import('../i18n.js');
const { renderStructuredPoolsTopology } = await import('../components/chassis-visualizer.js');

const lastToast = () => showToast.mock.calls.at(-1);
const lastConfirm = () => showConfirmToast.mock.calls.at(-1);
const POOLS = { is_observer_mode: false, platform: 'generic_linux', pools: [{ id: 'tank', name: 'tank', fs_type: 'btrfs', disks: [], status: 'ONLINE' }] };

describe('storage pool dialogs', () => {
  let box;
  beforeEach(async () => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="topo"></div>';
    box = document.getElementById('topo');
    vi.spyOn(api, 'get').mockResolvedValue(POOLS);
    renderStructuredPoolsTopology(box, POOLS);
    await setLanguage('en');
  });

  it('destroys a pool after asking, and says why it could not', async () => {
    box.querySelector('.btn-pool-destroy').click();
    const [title, msg, onOk, , opts] = lastConfirm();
    expect(title).toBe('Destroy Pool');
    expect(msg).toBe('Destroy pool "tank"? Its data is unmounted.');
    expect(opts.okText).toBe('Destroy Pool');
    const del = vi.spyOn(api, 'delete').mockRejectedValueOnce(new Error(''));
    await onOk();
    expect(lastToast()).toEqual(['Could not destroy the pool', 'error']);
    del.mockResolvedValueOnce({});
    await onOk();
    expect(lastToast()[1]).toBe('info');
  });

  it('ejects a pool, and offers to force it when the pool is busy', async () => {
    box.querySelector('.btn-pool-export').click();
    const [title, msg, onOk, , opts] = lastConfirm();
    expect(title).toBe('Safely Eject Pool');
    expect(msg).toContain('detach pool "tank"');
    expect(opts.okText).toBe('Safely Eject');
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({});
    await onOk();
    expect(lastToast()).toEqual(['Pool "tank" was ejected. You can unplug it now.', 'success']);

    post.mockRejectedValueOnce(new Error('target is busy; retry with force=true'));
    await onOk();
    const [ftitle, fmsg, forceOk, , fopts] = lastConfirm();
    expect(ftitle).toBe('Force eject pool');
    expect(fmsg).toContain('Eject and unmount it anyway?');
    expect(fopts.okText).toBe('Force eject');
    post.mockResolvedValueOnce({});
    await forceOk();
    expect(lastToast()).toEqual(['Pool "tank" was ejected.', 'success']);
    post.mockRejectedValueOnce(new Error(''));
    await forceOk();
    expect(lastToast()).toEqual(['Could not force-eject the pool', 'error']);

    post.mockRejectedValueOnce(new Error(''));
    await onOk();
    expect(lastToast()).toEqual(['Could not eject the pool', 'error']);
  });

  it('asks in German', async () => {
    await setLanguage('de');
    box.querySelector('.btn-pool-destroy').click();
    expect(lastConfirm()[0]).toBe('Pool zerstören');
    expect(lastConfirm()[1]).toBe('Pool „tank“ zerstören? Seine Daten werden ausgehängt.');
  });
});
