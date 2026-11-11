// SET-07: deleting a selection asks once, by name, and removes each app the way a single delete
// does. A selection does not outlive the filter it was made under.
import { describe, it, expect, beforeEach, vi } from 'vitest';

const asked = [];
vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showBottomSheet: vi.fn(),
  showDangerConfirm: vi.fn((title, text, onOk) => asked.push({ title, text, onOk })),
}));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { clearSelectedContainers, containerName, getSelectedContainerIds, runBulkContainerAction, selectAllContainers } from '../components/docker-table.js';

const view = { rerender: vi.fn(), refresh: vi.fn(async () => {}), updateBar: vi.fn() };

describe('deleting a selection of apps', () => {
  beforeEach(() => {
    asked.length = 0;
    clearSelectedContainers();
    vi.restoreAllMocks();
    document.body.innerHTML = `
      <button class="btn-container-act btn-docker-delete" data-id="c1" data-name="jellyfin"></button>
      <button class="btn-container-act btn-docker-delete" data-id="c2" data-name="paperless"></button>`;
  });

  it('names an app from its row, and falls back to a short id', () => {
    expect(containerName('c1')).toBe('jellyfin');
    expect(containerName('0123456789abcdef0123')).toBe('0123456789ab');
  });

  it('asks once and lists every name', async () => {
    selectAllContainers(['c1', 'c2']);
    const post = vi.spyOn(api, 'post');
    const del = vi.spyOn(api, 'delete');
    await runBulkContainerAction('delete', view);
    expect(asked).toHaveLength(1);
    expect(asked[0].text).toContain('jellyfin, paperless');
    expect(post).not.toHaveBeenCalled();
    expect(del).not.toHaveBeenCalled();
  });

  it('removes each app through the single delete, with its archive and without its folders', async () => {
    selectAllContainers(['c1', 'c2']);
    const post = vi.spyOn(api, 'post');
    const del = vi.spyOn(api, 'delete').mockResolvedValue({ success: true });
    await runBulkContainerAction('delete', view);
    await asked[0].onOk();
    expect(post).not.toHaveBeenCalled();
    expect(del.mock.calls.map((c) => c[0])).toEqual([
      '/api/docker/containers/c1?force=true&remove_volumes=false&archive_data=true',
      '/api/docker/containers/c2?force=true&remove_volumes=false&archive_data=true',
    ]);
    expect(del.mock.calls.every((c) => c[1]?.confirmed === true)).toBe(true);
    expect(getSelectedContainerIds()).toEqual([]);
    expect(view.refresh).toHaveBeenCalled();
  });

  it('says which app was not removed and goes on with the rest', async () => {
    selectAllContainers(['c1', 'c2']);
    const del = vi.spyOn(api, 'delete').mockRejectedValueOnce(new Error('in use')).mockResolvedValue({ success: true });
    await runBulkContainerAction('delete', view);
    await asked[0].onOk();
    expect(del).toHaveBeenCalledTimes(2);
    const last = /** @type {any} */ (showToast).mock.calls.at(-1);
    expect(last[0]).toContain('jellyfin: in use');
    expect(last[1]).toBe('error');
  });
});
