import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn() }, auth: {}, ApiError: class extends Error {} }));
import { api } from '../api.js';
import { showGettingStarted } from '../components/getting-started.js';
import { initWizardStepper, passwordStepProblem } from '../components/setup-wizard.js';

describe('Getting started checklist', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    localStorage.clear();
  });

  it('lists what is left with a button to the right place, and hides', async () => {
    api.get.mockResolvedValueOnce({ items: [{ id: 'password', open: 'system', done: true }, { id: 'share', open: 'mgmt-pane-storage-shares', done: false }], done: 1, total: 2, complete: false });
    window.openManagementSection = vi.fn();
    await showGettingStarted();
    const card = document.getElementById('getting-started-card');
    expect(card.textContent).toContain('1 of 2 done');
    card.querySelector('[data-gs-open]').click();
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-storage-shares');
    card.querySelector('[data-gs-hide]').click();
    expect(card.hidden).toBe(true);
    api.get.mockClear();
    await showGettingStarted();
    expect(api.get).not.toHaveBeenCalled(); // stays hidden until reopened
  });
});

describe('Setup wizard steps', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="setup-wizard-modal"><div class="smart-modal-body">
        <div id="b-welcome"></div><div id="b-hw"></div>
        <div id="b-pwd"><input id="setup-current-pwd"><input id="setup-new-pwd"><input id="setup-confirm-pwd"><div id="setup-wizard-err"></div></div>
        <div id="b-ups"></div><div id="b-alerts"></div>
        <div id="b-footer"><button id="setup-wizard-skip"></button><button id="setup-wizard-submit"></button></div>
      </div></div>`;
  });

  it('shows one step at a time and checks the password before moving on', () => {
    const s = initWizardStepper(document.getElementById('setup-wizard-modal'));
    expect(document.getElementById('b-pwd').hidden).toBe(true);
    expect(document.getElementById('setup-wizard-submit').hidden).toBe(true);
    document.getElementById('setup-wizard-next').click();
    expect(s.current).toBe(2);
    document.getElementById('setup-wizard-next').click();
    expect(s.current).toBe(2); // blocked: no password yet
    expect(document.getElementById('setup-wizard-err').textContent).not.toBe('');
    document.getElementById('setup-current-pwd').value = 'first-time-pass';
    document.getElementById('setup-new-pwd').value = 'My-New-Pass-1';
    document.getElementById('setup-confirm-pwd').value = 'My-New-Pass-1';
    expect(passwordStepProblem()).toBe('');
    document.getElementById('setup-wizard-next').click();
    expect(s.current).toBe(3);
    expect(document.getElementById('setup-wizard-submit').hidden).toBe(false);
  });
});
