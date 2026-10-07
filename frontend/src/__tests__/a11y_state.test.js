import { describe, it, expect, beforeEach, vi } from 'vitest';
import { state } from '../state.js';
import { ZettEventBus } from '../event-bus.js';
import { enhanceInteractiveElements } from '../a11y.js';

const nextFrame = () => new Promise((resolve) => requestAnimationFrame(resolve));

describe('Frontend Reactive State & EventBus', () => {
  beforeEach(() => {
    state.latestStats = null;
  });

  it('diffs incoming telemetry and emits stats:updated only when changed', async () => {
    const handler = vi.fn();
    ZettEventBus.on('stats:updated', handler);

    const initial = { cpu: { util: 12, temp: 42 }, mem: { pct: 50 } };
    state.setStats(initial);
    await nextFrame();
    expect(handler).toHaveBeenCalledTimes(1);

    // Call setStats with identical data
    state.setStats({ cpu: { util: 12, temp: 42 }, mem: { pct: 50 } });
    await nextFrame();
    expect(handler).toHaveBeenCalledTimes(1); // Should not have triggered again!

    // Call setStats with changed data
    state.setStats({ cpu: { util: 15, temp: 42 }, mem: { pct: 50 } });
    await nextFrame();
    expect(handler).toHaveBeenCalledTimes(2);
  });
});

describe('A11y Helper', () => {
  it('enhances non-semantic interactive elements with role and tabindex', () => {
    const container = document.createElement('div');
    container.innerHTML = `
      <div class="card card-cpu">CPU Card</div>
      <div class="disk" data-dev="sda">Disk 1</div>
      <div class="os-dock-item" data-action="open-dash">Dashboard</div>
      <button class="native-btn">Native</button>
    `;
    document.body.appendChild(container);

    enhanceInteractiveElements(container);

    const card = container.querySelector('.card');
    const disk = container.querySelector('.disk');
    const dockItem = container.querySelector('.os-dock-item');
    const nativeBtn = container.querySelector('.native-btn');

    expect(card.getAttribute('role')).toBe('button');
    expect(card.getAttribute('tabindex')).toBe('0');

    expect(disk.getAttribute('role')).toBe('button');
    expect(disk.getAttribute('tabindex')).toBe('0');

    expect(dockItem.getAttribute('role')).toBe('button');
    expect(dockItem.getAttribute('tabindex')).toBe('0');

    // Native button shouldn't need redundant role or tabindex added
    expect(nativeBtn.hasAttribute('role')).toBe(false);
  });
});
