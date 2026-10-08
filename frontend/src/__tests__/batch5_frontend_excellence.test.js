import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ZettEventBus } from '../event-bus.js';
import { bringToFront } from '../components/dock.js';
import { enhanceInteractiveElements } from '../a11y.js';

describe('Batch 5: Frontend Desktop OS & UX Excellence', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('event-bus bypasses rAF and dispatches immediately when document.hidden is true', () => {
    const listener = vi.fn();
    ZettEventBus.on('stats:updated', listener);

    // Mock document.hidden = true
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => true,
    });

    ZettEventBus.emit('stats:updated', { cpu: 45 });
    // In hidden tab, it should dispatch immediately without rAF queuing
    expect(listener).toHaveBeenCalledWith({ cpu: 45 }, expect.anything());

    // Restore document.hidden = false
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => false,
    });
  });

  it('a11y enhanceInteractiveElements populates aria-label using textContent', () => {
    const div = document.createElement('div');
    div.className = 'mgmt-action-btn';
    div.textContent = 'Active Service';
    document.body.appendChild(div);

    enhanceInteractiveElements(document.body);

    expect(div.getAttribute('role')).toBe('button');
    expect(div.getAttribute('tabindex')).toBe('0');
    expect(div.getAttribute('aria-label')).toBe('Active Service');
  });

  it('dock bringToFront treats container-inspector-window as a desktop app with dynamic z-index', () => {
    const inspector = document.createElement('div');
    inspector.id = 'container-inspector-window';
    inspector.className = 'container-inspector-window';
    document.body.appendChild(inspector);

    const prevZ = parseInt(inspector.style.zIndex || '0', 10);
    bringToFront(inspector);
    const newZ = parseInt(inspector.style.zIndex || '0', 10);

    // Should NOT be demoted to fixed modal z-index 9100
    expect(newZ).not.toBe(9100);
    expect(newZ).toBeGreaterThan(prevZ);
  });
});
