import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() }, auth: { getToken: vi.fn() }, ApiError: class extends Error {} }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

import { api } from '../api.js';
import { initSetupWizard } from '../components/setup-wizard.js';

describe('Setup wizard password change', () => {
  it('asks for the current password instead of assuming "admin"', async () => {
    document.body.innerHTML = `
      <div id="setup-wizard-modal" class="open">
        <input id="setup-current-pwd" value="">
        <input id="setup-new-pwd" value="Chosen-Pass-1">
        <input id="setup-confirm-pwd" value="Chosen-Pass-1">
        <div id="setup-wizard-err" style="display:none"></div>
        <button id="setup-wizard-submit">Save</button>
      </div>`;
    initSetupWizard();
    document.getElementById('setup-wizard-submit').click();
    await Promise.resolve();
    const err = document.getElementById('setup-wizard-err');
    expect(err.style.display).toBe('block');
    expect(err.textContent).toMatch(/current password/i);
    expect(api.post).not.toHaveBeenCalled();
  });
});
