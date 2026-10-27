import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { fetchAndRenderSecurityPosture } from '../components/management.js';
import { grantFolder } from '../components/setup-wizard.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

const posture = {
  score: 90,
  grade: 'A',
  checks: [
    { id: 'share_access_family', name: 'Kids', passed: false, details: 'kiddo', fix: 'share_access_family', fix_label: 'Fix kids' },
    { id: 'https_transport', name: 'HTTPS', passed: true, details: 'ok' },
  ],
};

describe('B11 safe defaults: Security Advisor fixes', () => {
  beforeEach(() => {
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    document.body.innerHTML = '<div id="sec-advisor-score-badge"></div><div id="sec-advisor-items"></div>';
  });
  afterEach(() => vi.restoreAllMocks());

  it('shows a fix button only where a fix exists, and applying it reloads the list', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue(posture);
    const post = vi.spyOn(api, 'post').mockResolvedValue({ ok: true, message: 'Done for kids.' });
    await fetchAndRenderSecurityPosture();
    const buttons = document.querySelectorAll('.sec-advisor-fix-btn');
    expect(buttons).toHaveLength(1);
    buttons[0].click();
    await vi.waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(post).toHaveBeenCalledWith('/api/system/security-posture/fix/share_access_family', {});
    expect(toast.showToast).toHaveBeenCalledWith('Done for kids.', 'success');
  });

  it('says nothing when the person cancels the confirmation', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(posture);
    vi.spyOn(api, 'post').mockRejectedValue(Object.assign(new Error('cancelled'), { error: 'cancelled' }));
    await fetchAndRenderSecurityPosture();
    document.querySelector('.sec-advisor-fix-btn').click();
    await vi.waitFor(() => expect(document.querySelector('.sec-advisor-fix-btn').disabled).toBe(false));
    expect(toast.showToast).not.toHaveBeenCalled();
  });
});

describe('B11 safe defaults: setup wizard', () => {
  afterEach(() => vi.restoreAllMocks());

  it('gives the new person the folder the wizard made, keeping other grants', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      shares: [
        { name: 'Family', path: '/mnt/user/Family', users: {} },
        { name: 'media', path: '/mnt/user/media', users: { bob: 'read' }, default: 'read' },
      ],
    });
    const put = vi.spyOn(api, 'put').mockResolvedValue({});
    await grantFolder('Family', 'Ann');
    expect(put).toHaveBeenCalledWith('/api/storage/share-access', {
      shares: {
        Family: { users: { ann: 'write' } },
        media: { users: { bob: 'read' }, default: 'read' },
      },
    });
  });

  it('warns but does not throw when the grant fails', async () => {
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    vi.spyOn(api, 'get').mockRejectedValue(new Error('offline'));
    await grantFolder('Family', 'Ann');
    expect(toast.showToast).toHaveBeenCalledWith(expect.stringContaining('Ann'), 'warning');
  });
});
