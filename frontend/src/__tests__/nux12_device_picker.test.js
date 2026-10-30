import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));

import { api } from '../api.js';
import { devicePicker } from '../components/family-filter.js';

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("picking a child's devices (NUX-12)", () => {
  it('lists what AdGuard has seen and adds or removes them', async () => {
    api.get.mockResolvedValue({ devices: [{ id: '192.0.2.20', name: 'lenas-tablet' }, { id: '192.0.2.21', name: '192.0.2.21' }] });
    const input = document.createElement('input');
    input.value = '192.0.2.21';
    const box = devicePicker(input);
    box.querySelector('button').click();
    await flush();
    const boxes = box.querySelectorAll('input[type=checkbox]');
    expect(box.textContent).toContain('lenas-tablet (192.0.2.20)');
    expect(boxes[1].checked).toBe(true);
    boxes[0].checked = true;
    boxes[0].dispatchEvent(new Event('change'));
    expect(input.value).toBe('192.0.2.21, 192.0.2.20');
    boxes[1].checked = false;
    boxes[1].dispatchEvent(new Event('change'));
    expect(input.value).toBe('192.0.2.20');
    box.querySelector('button').click();
    expect(box.querySelector('.ff-picker-list').hidden).toBe(true);
  });

  it('says why there are none', async () => {
    api.get.mockResolvedValue({ devices: [], error: 'Connect AdGuard Home first.' });
    const box = devicePicker(document.createElement('input'));
    box.querySelector('button').click();
    await flush();
    expect(box.textContent).toContain('Connect AdGuard Home first.');
    api.get.mockRejectedValue(new Error('offline'));
    const box2 = devicePicker(document.createElement('input'));
    box2.querySelector('button').click();
    await flush();
    expect(box2.textContent).toContain('offline');
  });
});
