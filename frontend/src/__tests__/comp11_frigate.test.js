import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { frigateBody, readForm, stateText, renderFrigateEvents } from '../components/frigate-events.js';

const INFO = {
  enabled: true,
  url: 'http://frigate:5000',
  labels: ['person'],
  cameras: ['front'],
  min_score: 0.7,
  cooldown_min: 5,
  last_check: 1000,
  last_error: '',
  choices: ['person', 'car', 'dog'],
};

describe('camera alerts from Frigate (COMP-11)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('says whether it runs', () => {
    expect(stateText({ enabled: false })).toBe('Off');
    expect(stateText({ enabled: true, last_error: 'Frigate didn\'t answer' })).toContain("didn't answer");
    expect(stateText({ enabled: true, last_check: 0 })).toContain('within a minute');
    expect(stateText(INFO, 1000 + 3 * 60)).toContain('3 minutes ago');
    expect(stateText(INFO, 1010)).toContain('just now');
  });

  it('reads the form back into the settings', () => {
    const mount = document.createElement('div');
    mount.append(frigateBody(INFO));
    const boxes = mount.querySelectorAll('input[name="label"]');
    expect(boxes.length).toBe(3);
    /** @type {HTMLInputElement} */ (boxes[1]).checked = true;
    /** @type {HTMLInputElement} */ (mount.querySelector('[name="cameras"]')).value = 'front, back ,';
    /** @type {HTMLInputElement} */ (mount.querySelector('[name="min_score"]')).value = '80';
    expect(readForm(mount)).toEqual({
      enabled: true,
      url: 'http://frigate:5000',
      labels: ['person', 'car'],
      cameras: ['front', 'back'],
      min_score: 0.8,
      cooldown_min: 5,
    });
  });

  it('saves and checks Frigate', async () => {
    api.get.mockResolvedValue(INFO);
    api.put.mockResolvedValue({});
    api.post.mockResolvedValue({ ok: true, version: '0.16.2', cameras: ['back', 'front'] });
    const mount = document.createElement('div');
    document.body.append(mount);
    await renderFrigateEvents(mount);
    /** @type {HTMLElement} */ (mount.querySelector('[data-frigate="test"]')).click();
    await vi.waitFor(() => expect(mount.querySelector('.frigate-test').textContent).toContain('2 cameras: back, front'));
    /** @type {HTMLElement} */ (mount.querySelector('[data-frigate="save"]')).click();
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/notifications/frigate', expect.objectContaining({ labels: ['person'] })));
    expect(showToast).toHaveBeenCalledWith('Camera alert settings saved.', 'success');
  });

  it('shows a failed check and a failed load', async () => {
    api.get.mockResolvedValueOnce(INFO);
    api.post.mockResolvedValue({ ok: false, error: 'Frigate didn\'t answer at http://frigate:5000' });
    const mount = document.createElement('div');
    await renderFrigateEvents(mount);
    /** @type {HTMLElement} */ (mount.querySelector('[data-frigate="test"]')).click();
    await vi.waitFor(() => expect(mount.querySelector('.frigate-test').textContent).toContain("didn't answer"));
    api.get.mockRejectedValueOnce(new Error('forbidden'));
    await renderFrigateEvents(mount);
    expect(mount.textContent).toContain("forbidden"); // with a sentence and Retry (NUX-14)
    expect(mount.querySelector(".zn-load-error button")).not.toBeNull();
    await renderFrigateEvents(null);
  });
});
