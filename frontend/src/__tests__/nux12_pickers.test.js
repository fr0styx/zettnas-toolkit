import { describe, it, expect, vi } from 'vitest';

vi.mock('../i18n.js', () => ({ getLanguage: () => 'en', t: (k, f, p = {}) => String(f).replace(/\{(\w+)\}/g, (m, x) => (x in p ? p[x] : m)) }));
const get = vi.fn();
vi.mock('../api.js', () => ({ api: { get: (...a) => get(...a), put: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));

const { cameraChoices } = await import('../components/frigate-events.js');
const { remoteNames } = await import('../components/two-way-sync.js');

describe('pickers instead of typing (NUX-12)', () => {
  it('turns the camera field into checkboxes once Frigate names them', () => {
    const mount = document.createElement('div');
    mount.innerHTML = '<label>Cameras <input name="cameras" value="door"></label><div class="frigate-cams"></div>';
    cameraChoices(mount, ['door', 'garden']);
    const boxes = [...mount.querySelectorAll('.frigate-cams input')];
    expect(boxes.map((b) => b.checked)).toEqual([true, false]);
    expect(mount.querySelector('label').hasAttribute('hidden')).toBe(true);
    boxes[1].checked = true;
    boxes[1].dispatchEvent(new Event('change'));
    expect(mount.querySelector('[name="cameras"]').value).toBe(''); // every camera
    boxes[0].checked = false;
    boxes[0].dispatchEvent(new Event('change'));
    expect(mount.querySelector('[name="cameras"]').value).toBe('garden');
  });

  it('suggests the cloud remotes already set up', async () => {
    get.mockResolvedValueOnce([{ name: 'gdrive' }, { name: 'b2' }]);
    expect(await remoteNames()).toEqual(['gdrive', 'b2']);
    get.mockRejectedValueOnce(new Error('forbidden'));
    expect(await remoteNames()).toEqual([]);
  });
});
