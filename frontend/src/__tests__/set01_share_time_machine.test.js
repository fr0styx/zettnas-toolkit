import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { openCreateNetworkShareModal } from '../components/chassis-visualizer.js';
import { api } from '../api.js';

const flush = () => new Promise((r) => setTimeout(r, 0));
const el = (id) => document.getElementById(id);

describe('Time Machine is one request with a size limit (SET-01)', () => {
  let post;
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="modal-create-network-share" class="smart-modal-backdrop" style="display:none;">
        <div class="smart-modal-window">
          <div class="smart-modal-header"><button id="modal-create-share-close-btn"></button></div>
          <form id="create-share-form">
            <input id="create-share-name" value="macbackup" />
            <input id="create-share-path" value="" />
            <input id="create-share-comment" value="" />
            <input id="create-share-quota-gb" value="" />
            <select id="create-share-security"><option value="private" selected>Private</option></select>
            <input type="checkbox" id="create-share-readonly" />
            <input type="checkbox" id="create-share-export-smb" checked />
            <input type="checkbox" id="create-share-export-nfs" />
            <input type="checkbox" id="create-share-timemachine" checked />
            <div id="create-share-error-box" style="display:none;"></div>
            <button type="button" id="modal-create-share-cancel-btn">Cancel</button>
            <button type="submit" id="create-share-submit-btn">Submit</button>
          </form>
        </div>
      </div>`;
    vi.spyOn(api, 'get').mockResolvedValue([]);
    post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'created' });
  });
  afterEach(() => vi.restoreAllMocks());

  const submit = async () => {
    el('create-share-form').dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    await flush();
  };

  it('asks for a size limit before anything is sent', async () => {
    openCreateNetworkShareModal();
    await submit();
    expect(post).not.toHaveBeenCalled();
    expect(el('create-share-error-box').style.display).toBe('block');
    expect(el('create-share-error-box').textContent).toContain('size limit');
  });

  it('sends one request that carries the choice and the limit', async () => {
    openCreateNetworkShareModal();
    el('create-share-quota-gb').value = '500';
    await submit();
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith('/api/storage/shares', expect.objectContaining({ name: 'macbackup', timemachine: true, quota_gb: 500 }));
    expect(post.mock.calls.some((c) => c[0] === '/api/samba/shares')).toBe(false);
  });

  it('sends timemachine: false for an ordinary folder', async () => {
    el('create-share-timemachine').checked = false;
    openCreateNetworkShareModal();
    await submit();
    expect(post).toHaveBeenCalledWith('/api/storage/shares', expect.objectContaining({ timemachine: false }));
  });
});
