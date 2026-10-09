import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { getThermalLevel } from '../components/chassis-visualizer.js';
import { syncDesktopThemeUI, initDesktopThemeControls } from '../components/settings.js';
import { state } from '../state.js';

describe('Batch 1: Accessibility, Form Label Linking & ARIA Radiogroups', () => {
  let htmlDoc;

  beforeEach(() => {
    const htmlPath = resolve(__dirname, '../../index.html');
    const htmlContent = readFileSync(htmlPath, 'utf-8');
    const parser = new DOMParser();
    htmlDoc = parser.parseFromString(htmlContent, 'text/html');
  });

  it('verifies explicit label for attributes match target input/select IDs across all forms', () => {
    const expectedPairs = [
      { labelFor: 'sec-username', inputId: 'sec-username' },
      { labelFor: 'sec-email', inputId: 'sec-email' },
      { labelFor: 'sec-new-pwd', inputId: 'sec-new-pwd' },
      { labelFor: 'sec-confirm-pwd', inputId: 'sec-confirm-pwd' },
      { labelFor: 'sec-cur-pwd', inputId: 'sec-cur-pwd' },
      { labelFor: 'notif-master-enabled', inputId: 'notif-master-enabled' },
      { labelFor: 'notif-toggle-smart', inputId: 'notif-toggle-smart' },
      { labelFor: 'notif-toggle-temp', inputId: 'notif-toggle-temp' },
      { labelFor: 'notif-toggle-ups', inputId: 'notif-toggle-ups' },
      { labelFor: 'notif-toggle-fan', inputId: 'notif-toggle-fan' },
      { labelFor: 'notif-toggle-copy', inputId: 'notif-toggle-copy' },
      { labelFor: 'notif-toggle-container', inputId: 'notif-toggle-container' },
      { labelFor: 'notif-toggle-backup', inputId: 'notif-toggle-backup' },
      { labelFor: 'notif-input-hdd-temp', inputId: 'notif-input-hdd-temp' },
      { labelFor: 'notif-input-cpu-temp', inputId: 'notif-input-cpu-temp' },
      { labelFor: 'notif-input-cooldown', inputId: 'notif-input-cooldown' },
      { labelFor: 'webdav-cfg-port', inputId: 'webdav-cfg-port' },
      { labelFor: 'webdav-cfg-root', inputId: 'webdav-cfg-root' },
      { labelFor: 'webdav-cfg-user', inputId: 'webdav-cfg-user' },
      { labelFor: 'webdav-cfg-pass', inputId: 'webdav-cfg-pass' },
      { labelFor: 'new-remote-provider-select', inputId: 'new-remote-provider-select' },
      { labelFor: 'new-remote-name', inputId: 'new-remote-name' },
      { labelFor: 'create-pool-name', inputId: 'create-pool-name' },
      { labelFor: 'create-pool-fs', inputId: 'create-pool-fs' },
      { labelFor: 'create-pool-profile', inputId: 'create-pool-profile' },
      { labelFor: 'create-pool-compression', inputId: 'create-pool-compression' },
      { labelFor: 'create-pool-mountpoint', inputId: 'create-pool-mountpoint' },
      { labelFor: 'create-share-name', inputId: 'create-share-name' },
      { labelFor: 'create-share-security', inputId: 'create-share-security' },
      { labelFor: 'create-share-path', inputId: 'create-share-path' },
      { labelFor: 'create-share-comment', inputId: 'create-share-comment' },
      { labelFor: 'snap-name-input', inputId: 'snap-name-input' }
    ];

    expectedPairs.forEach(({ labelFor, inputId }) => {
      const label = htmlDoc.querySelector(`label[for="${labelFor}"]`);
      expect(label, `Label for="${labelFor}" must exist`).not.toBeNull();
      const input = htmlDoc.getElementById(inputId);
      expect(input, `Input/select #${inputId} must exist`).not.toBeNull();
    });
  });

  it('verifies ARIA radiogroup roles and aria-checked attributes on Acoustic Fan Profiles', () => {
    const row = htmlDoc.querySelector('.profile-switcher-row');
    expect(row).not.toBeNull();
    expect(row.getAttribute('role')).toBe('radiogroup');
    expect(row.getAttribute('aria-label')).toBeTruthy();

    const buttons = row.querySelectorAll('.profile-btn');
    expect(buttons.length).toBe(4);
    buttons.forEach((btn) => {
      expect(btn.getAttribute('role')).toBe('radio');
      expect(btn.hasAttribute('aria-checked')).toBe(true);
    });

    const activeBtn = row.querySelector('.profile-btn.active');
    expect(activeBtn).not.toBeNull();
    expect(activeBtn.getAttribute('aria-checked')).toBe('true');
  });

  it('verifies ARIA radiogroup roles and aria-checked attributes on Desktop Theme Presets', () => {
    const grid = htmlDoc.querySelector('.theme-palette-grid');
    expect(grid).not.toBeNull();
    expect(grid.getAttribute('role')).toBe('radiogroup');
    expect(grid.getAttribute('aria-label')).toBeTruthy();

    const presets = grid.querySelectorAll('.desktop-theme-preset');
    expect(presets.length).toBeGreaterThanOrEqual(8);
    presets.forEach((btn) => {
      expect(btn.getAttribute('role')).toBe('radio');
      expect(btn.hasAttribute('aria-checked')).toBe(true);
      expect(btn.hasAttribute('aria-label')).toBe(true);
    });
  });

  it('verifies syncDesktopThemeUI updates aria-checked dynamically', () => {
    document.body.innerHTML = `
      <div id="mgmt-pane-theme">
        <div class="theme-palette-grid" role="radiogroup">
          <button class="desktop-theme-preset" data-theme-id="cyber" role="radio" aria-checked="false"></button>
          <button class="desktop-theme-preset" data-theme-id="amber" role="radio" aria-checked="false"></button>
          <button class="desktop-theme-preset" data-theme-id="emerald" role="radio" aria-checked="false"></button>
        </div>
        <span id="desktop-theme-active-badge"></span>
      </div>
    `;

    state.desktopTheme = 'amber';
    syncDesktopThemeUI();

    const amberBtn = document.querySelector('.desktop-theme-preset[data-theme-id="amber"]');
    const cyberBtn = document.querySelector('.desktop-theme-preset[data-theme-id="cyber"]');

    expect(amberBtn.classList.contains('active')).toBe(true);
    expect(amberBtn.getAttribute('aria-checked')).toBe('true');
    expect(cyberBtn.classList.contains('active')).toBe(false);
    expect(cyberBtn.getAttribute('aria-checked')).toBe('false');
  });

  it('verifies initDesktopThemeControls supports keyboard arrow navigation', () => {
    document.body.innerHTML = `
      <div id="mgmt-pane-theme">
        <div class="theme-palette-grid" role="radiogroup">
          <button class="desktop-theme-preset active" data-theme-id="cyber" role="radio" aria-checked="true"></button>
          <button class="desktop-theme-preset" data-theme-id="amber" role="radio" aria-checked="false"></button>
          <button class="desktop-theme-preset" data-theme-id="emerald" role="radio" aria-checked="false"></button>
        </div>
        <span id="desktop-theme-active-badge"></span>
      </div>
    `;

    initDesktopThemeControls();

    const cyberBtn = document.querySelector('.desktop-theme-preset[data-theme-id="cyber"]');
    const amberBtn = document.querySelector('.desktop-theme-preset[data-theme-id="amber"]');

    // Simulate ArrowRight on cyberBtn
    const arrowRightEvent = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true });
    cyberBtn.dispatchEvent(arrowRightEvent);

    expect(state.desktopTheme).toBe('amber');
    expect(amberBtn.classList.contains('active')).toBe(true);
    expect(amberBtn.getAttribute('aria-checked')).toBe('true');
  });

  it('verifies getThermalLevel returns CSS variables for theme-aware tokens', () => {
    const cool = getThermalLevel(25, false);
    expect(cool.color).toBe('var(--brand, #38bdf8)');
    expect(cool.cls).toBe('cool');

    const ok = getThermalLevel(40, false);
    expect(ok.color).toBe('var(--ok, #3bf58b)');
    expect(ok.cls).toBe('ok');

    const warn = getThermalLevel(48, false);
    expect(warn.color).toBe('var(--warn, #f5b731)');
    expect(warn.cls).toBe('warn');

    const crit = getThermalLevel(58, false);
    expect(crit.color).toBe('var(--crit, #f0553b)');
    expect(crit.cls).toBe('crit');

    const standby = getThermalLevel(null, true);
    expect(standby.color).toBe('var(--muted, #64748b)');
    expect(standby.cls).toBe('standby');
  });
});
