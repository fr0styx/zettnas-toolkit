import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() } }));

import { api } from '../api.js';
import { whoText, peopleForm } from '../components/encrypted-folders.js';

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('who may open an encrypted folder (NSEC-5)', () => {
  it('says it in words', () => {
    expect(whoText({ share: 'Family', people: null })).toBe('Everyone who may use Family can open it');
    expect(whoText({ share: 'Family', people: ['Mum', 'mia'] })).toBe('Only Mum, mia can open it');
  });

  it('chooses people, or everyone with the share', async () => {
    api.get.mockResolvedValue([{ username: 'Mum', display_name: 'Mum' }, { username: 'mia', display_name: 'Mia' }]);
    api.put.mockResolvedValue({ people: ['Mum', 'mia'] });
    const mount = document.createElement('div');
    const row = document.createElement('div');
    row.dataset.name = 'Medical';
    row.dataset.people = JSON.stringify(['Mum']);
    const actions = document.createElement('div');
    actions.className = 'ef-actions';
    row.append(actions);
    mount.append(row);
    const form = await peopleForm(mount, row);
    const boxes = [...form.querySelectorAll('input[name=person]')];
    expect(boxes.map((b) => b.checked)).toEqual([true, false]);
    boxes[1].checked = true;
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(api.put).toHaveBeenCalledWith('/api/encrypted-folders/Medical/people', { people: ['Mum', 'mia'] });
    const everyone = form.querySelector('input[name=everyone]');
    everyone.checked = true;
    everyone.dispatchEvent(new Event('change'));
    expect(boxes[0].disabled).toBe(true);
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(api.put).toHaveBeenLastCalledWith('/api/encrypted-folders/Medical/people', { people: null });
  });

  it('says so when the accounts cannot be read', async () => {
    api.get.mockRejectedValue(new Error('no'));
    const row = document.createElement('div');
    expect(await peopleForm(document.createElement('div'), row)).toBe(null);
  });
});
