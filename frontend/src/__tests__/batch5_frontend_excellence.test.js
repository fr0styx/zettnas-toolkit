import { readStyleCss } from './helpers/read-style-css.js';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ZettEventBus } from '../event-bus.js';
import { bringToFront } from '../components/dock.js';
import { enhanceInteractiveElements } from '../a11y.js';
import { trapFocus } from '../utils.js';
import { t, setLanguage } from '../i18n.js';
import fs from 'fs';
import path from 'path';

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

  it('a11y enhanceInteractiveElements uses visible text as the name (no duplicate aria-label)', () => {
    const div = document.createElement('div');
    div.className = 'mgmt-action-btn';
    div.textContent = 'Active Service';
    document.body.appendChild(div);

    enhanceInteractiveElements(document.body);

    expect(div.getAttribute('role')).toBe('button');
    expect(div.getAttribute('tabindex')).toBe('0');
    expect(div.hasAttribute('aria-label')).toBe(false); // FE-10: visible text already names it
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

  it('trapFocus dynamically traps focus, ignores disabled elements, and executes onClose on Escape', () => {
    const modal = document.createElement('div');
    modal.innerHTML = `
      <button id="btn-1">Button 1</button>
      <button id="btn-disabled" disabled>Disabled</button>
      <input id="input-1" type="text" />
      <button id="btn-close">Close</button>
    `;
    document.body.appendChild(modal);

    const onClose = vi.fn();
    const unbind = trapFocus(modal, onClose);

    const btn1 = document.getElementById('btn-1');
    const btnClose = document.getElementById('btn-close');

    // Simulate Tab on last focusable element wrapping to first
    btnClose.focus();
    const tabEvent = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    modal.dispatchEvent(tabEvent);
    expect(document.activeElement).toBe(btn1);

    // Simulate Escape calling onClose
    const escEvent = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    modal.dispatchEvent(escEvent);
    expect(onClose).toHaveBeenCalled();

    unbind();
  });

  it('i18n t() supports parameterized template interpolation', () => {
    setLanguage('en');
    const res = t('fm.uploading_toast', 'Uploading {count} file(s)...', { count: 3 });
    expect(res).toBe('Uploading 3 files…'); // a plural rule (UX-35)
    expect(t('fm.uploading_toast', '', { count: 1 })).toBe('Uploading 1 file…');

    const remoteRes = t('remotes.deleted', "Remote '{name}' deleted successfully.", { name: 'G陀Drive' });
    expect(remoteRes).toContain('G陀Drive');
  });

  it('index.html viewport meta tag permits zoom and user scaling for WCAG AA compliance', () => {
    const indexPath = path.resolve(__dirname, '../../index.html');
    const html = fs.readFileSync(indexPath, 'utf-8');

    expect(html).not.toContain('user-scalable=no');
    expect(html).not.toContain('maximum-scale=1');
    expect(html).toContain('name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"');
  });

  it('style.css provides >= 4.5:1 accessible contrast tokens for muted text', () => {
    const css = readStyleCss();

    // Amethyst theme muted token
    expect(css).toContain('--muted: #b399cf;');
    // Crimson theme muted token
    expect(css).toContain('--muted: #c48995;');
    // Emerald LCD theme muted token
    expect(css).toContain('--muted: #38b56f;');
    // Cyber LCD theme muted token
    expect(css).toContain('--muted: #94a3b8;');
  });
});
