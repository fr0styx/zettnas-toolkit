import { readStyleCss } from './helpers/read-style-css.js';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ALL_TRANSLATIONS as TRANSLATIONS } from '../locales/all.js';
import { DockManager, initDockSystem } from '../components/dock.js';
import { FileManagerWindow } from '../components/file-manager.js';
import { openFilePreviewModal, closeFilePreviewModal } from '../components/file-preview-modal.js';
import fs from 'fs';
import path from 'path';

describe('Batch 5: Performance, WAI-ARIA, Keyboard Ergonomics & i18n Verification Suite', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  afterEach(() => {
    closeFilePreviewModal();
    vi.restoreAllMocks();
  });

  it('1. Dictionary Parity: All 5 languages (EN, DE, ZH, FR, ES) have 100% identical key parity', () => {
    const langs = ['en', 'de', 'zh', 'fr', 'es'];
    expect(Object.keys(TRANSLATIONS)).toEqual(expect.arrayContaining(langs));

    const enKeys = new Set(Object.keys(TRANSLATIONS['en']));
    expect(enKeys.size).toBeGreaterThanOrEqual(1100);

    for (const lang of ['de', 'zh', 'fr', 'es']) {
      const currentKeys = new Set(Object.keys(TRANSLATIONS[lang]));
      const missing = [...enKeys].filter((k) => !currentKeys.has(k));
      expect(missing, `Missing keys in ${lang}`).toEqual([]);
      expect(currentKeys.size, `Key count match for ${lang}`).toBe(enKeys.size);
    }
  });

  it('2. Dock Roving Tabindex: initial render sets tabindex="0" on first item and "-1" on others', () => {
    const dockContainer = document.createElement('div');
    dockContainer.id = 'os-dock-container';
    const dock = document.createElement('div');
    dock.id = 'os-dock';
    dockContainer.appendChild(dock);
    document.body.appendChild(dockContainer);

    initDockSystem();
    const items = Array.from(dock.querySelectorAll('.dock-item'));
    expect(items.length).toBeGreaterThan(1);
    expect(items[0].getAttribute('tabindex')).toBe('0');
    for (let i = 1; i < items.length; i++) {
      expect(items[i].getAttribute('tabindex')).toBe('-1');
    }

    expect(dock.getAttribute('role')).toBe('toolbar');

    // Arrow navigation moves tabindex
    items[0].focus();
    dock.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(items[0].getAttribute('tabindex')).toBe('-1');
    expect(items[1].getAttribute('tabindex')).toBe('0');
  });

  it('3. File Explorer: list view and grid view enforce role="grid", role="row", and aria-selected', () => {
    const win = document.createElement('div');
    win.id = 'fe-test-win';
    win.className = 'file-manager-window active-window';
    win.innerHTML = `
      <div class="fm-viewport">
        <div class="fm-spacer"></div>
        <div class="fm-list"></div>
      </div>
    `;
    document.body.appendChild(win);

    const fm = new FileManagerWindow('fe-test-win', 'fm-test', '/mnt/user', false);
    fm.windowEl = win;
    fm.viewport = win.querySelector('.fm-viewport');
    fm.spacer = win.querySelector('.fm-spacer');
    fm.list = win.querySelector('.fm-list');
    fm.fileList = [
      { name: 'document.pdf', path: '/mnt/user/document.pdf', is_dir: false, size: 2048 },
      { name: 'photos', path: '/mnt/user/photos', is_dir: true, size: 4096 }
    ];

    // Grid / Icon view
    fm.viewMode = 'icon';
    fm.selectedPaths.add('/mnt/user/document.pdf');
    fm.renderViewport();

    expect(fm.list.getAttribute('role')).toBe('grid');
    const cards = fm.list.querySelectorAll('.fm-grid-card');
    expect(cards.length).toBe(2);
    expect(cards[0].getAttribute('role')).toBe('row');
    expect(cards[0].getAttribute('aria-selected')).toBe('true');
    expect(cards[0].getAttribute('tabindex')).toBe('0');
    expect(cards[1].getAttribute('aria-selected')).toBe('false');
    expect(cards[1].getAttribute('tabindex')).toBe('-1');

    // List view
    fm.viewMode = 'list';
    fm.renderViewport();
    expect(fm.list.getAttribute('role')).toBe('grid');
    const rows = fm.list.querySelectorAll('.fm-row');
    expect(rows.length).toBe(2);
    expect(rows[0].getAttribute('role')).toBe('row');
    expect(rows[0].getAttribute('aria-selected')).toBe('true');
    expect(rows[0].getAttribute('tabindex')).toBe('0');
    expect(rows[1].getAttribute('aria-selected')).toBe('false');
    expect(rows[1].getAttribute('tabindex')).toBe('-1');
  });

  it('4. File Explorer Keyboard Ergonomics: F2 triggers rename and Ctrl+F focuses search input', () => {
    const win = document.createElement('div');
    win.id = 'fe-test-win-kb';
    win.className = 'file-manager-window active-window';
    win.innerHTML = `
      <input type="text" class="fm-search-input" />
      <div class="fm-viewport">
        <div class="fm-spacer"></div>
        <div class="fm-list"></div>
      </div>
    `;
    document.body.appendChild(win);

    const fm = new FileManagerWindow('fe-test-win-kb', 'fm-test-kb', '/mnt/user', false);
    fm.windowEl = win;
    fm.searchInput = win.querySelector('.fm-search-input');
    fm.fileList = [{ name: 'report.txt', path: '/mnt/user/report.txt', is_dir: false, size: 500 }];
    fm.selectedPaths.add('/mnt/user/report.txt');

    const handleActionSpy = vi.spyOn(fm, 'handleAction').mockImplementation(() => {});

    // F2 triggers rename
    const f2Event = new KeyboardEvent('keydown', { key: 'F2', cancelable: true });
    fm.handleKeydown(f2Event);
    expect(handleActionSpy).toHaveBeenCalledWith('rename', '/mnt/user/report.txt', 'report.txt');
    expect(f2Event.defaultPrevented).toBe(true);

    // Ctrl+F focuses search input
    const ctrlFEvent = new KeyboardEvent('keydown', { key: 'f', ctrlKey: true, cancelable: true });
    const searchFocusSpy = vi.spyOn(fm.searchInput, 'focus');
    fm.handleKeydown(ctrlFEvent);
    expect(searchFocusSpy).toHaveBeenCalled();
    expect(ctrlFEvent.defaultPrevented).toBe(true);
  });

  it('5. Quick Look Modal: Escape key cleanly unbinds and permits repeat opening without leaks', async () => {
    const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener');

    await openFilePreviewModal('/mnt/user/test.txt', 'test.txt');
    const overlay = document.getElementById('quicklook-modal-overlay');
    expect(overlay).not.toBeNull();

    // Trigger close via Escape
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(document.getElementById('quicklook-modal-overlay')).toBeNull();
    expect(removeEventListenerSpy).toHaveBeenCalledWith('keydown', expect.any(Function));

    // Open again immediately to ensure repeated opening works cleanly
    await openFilePreviewModal('/mnt/user/test.txt', 'test.txt');
    expect(document.getElementById('quicklook-modal-overlay')).not.toBeNull();
    closeFilePreviewModal();
    expect(document.getElementById('quicklook-modal-overlay')).toBeNull();
  });

  it('6. Theme Contrast & CSS Compositing Rules: verify CSS tokens in style.css', () => {
    const css = readStyleCss();

    // Root contrast & fonts
    expect(css).toContain('--muted:#8493a5;');
    expect(css).toContain('--font-sans:');
    expect(css).toContain('--font-mono:');

    // UX-33: accent themes keep the standard status colours; the Yak theme has its own
    expect(css).not.toMatch(/body\.theme-amber\s*\{[^}]*?--crit:/);
    expect(css).toMatch(/body\.theme-yak\s*\{[^}]*?--crit:\s*#ff6b6b;/);

    // .window-dragging compositing rules
    expect(css).toContain('.window-dragging');
    expect(css).toContain('backdrop-filter: none !important;');
    expect(css).toContain('pointer-events: none !important;');

    // .mgmt-tab-pane content-visibility
    expect(css).toContain('content-visibility: auto;');
    expect(css).toContain('contain-intrinsic-size: auto none auto 500px;');
  });
});
