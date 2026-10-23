import { describe, it, expect, beforeEach, vi } from 'vitest';
import { initSetupWizard, openSetupWizard } from '../components/setup-wizard.js';
import { formatAnsiToHtml } from '../components/vm-manager.js';
import { state } from '../state.js';

describe('Batch 7: Consumer-Grade Differentiators Frontend Tests', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="setup-wizard-modal" class="smart-modal-backdrop">
        <div class="smart-modal-window">
          <button id="setup-wizard-close" class="modal-close-btn"></button>
          <button id="setup-wizard-skip">Skip for now</button>
          <button id="setup-wizard-submit">Complete Setup & Save</button>
          <span id="setup-hw-chassis"></span>
          <span id="setup-hw-fb"></span>
          <span id="setup-hw-fans"></span>
          <input type="password" id="setup-current-pwd" value="" />
          <input type="password" id="setup-new-pwd" value="" />
          <input type="password" id="setup-confirm-pwd" value="" />
          <div id="setup-wizard-err" style="display:none;"></div>
        </div>
      </div>
      <div id="sec-advisor-score-badge"></div>
      <div id="sec-advisor-items"></div>
      <div id="sec-default-pwd-warning" style="display:none;"></div>
    `;

    state.stats = {
      chassis: 'd4',
      chassis_label: 'Zettlab D4 (4-Bay)',
      security: {
        is_default_password: true,
      },
      fans: [1200, 1150],
      peripherals: {
        fb_active: true,
      }
    };
    state.isLcdDirect = false;
  });

  it('enforces mandatory password rotation on first setup and hides dismissal buttons', () => {
    initSetupWizard();
    openSetupWizard(state.stats);

    const modal = document.getElementById('setup-wizard-modal');
    const skipBtn = document.getElementById('setup-wizard-skip');
    const closeBtn = document.getElementById('setup-wizard-close');

    expect(modal).not.toBeNull();
    // When is_default_password is true, skip and close must be hidden
    expect(skipBtn.style.display).toBe('none');
    expect(closeBtn.style.display).toBe('none');

    const hwChassis = document.getElementById('setup-hw-chassis');
    expect(hwChassis.textContent).toBe('Zettlab D4 (4-Bay)');
  });

  it('allows dismissal when password is not default', () => {
    state.stats.security.is_default_password = false;
    openSetupWizard(state.stats);

    const skipBtn = document.getElementById('setup-wizard-skip');
    const closeBtn = document.getElementById('setup-wizard-close');

    expect(skipBtn.style.display).toBe('inline-block');
    expect(closeBtn.style.display).toBe('inline-block');
  });

  it('formats ANSI color sequences to secure styled HTML in terminal output', () => {
    const rawAnsi = '\x1b[32m[OK]\x1b[0m Container started in \x1b[33m120ms\x1b[0m';
    const html = formatAnsiToHtml(rawAnsi);

    expect(html).toContain('[OK]');
    expect(html).toContain('Container started in');
    expect(html).toContain('120ms');
    expect(html).toContain('<span');
  });
});
