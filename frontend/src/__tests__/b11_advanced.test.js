import { describe, it, expect, vi, beforeEach } from 'vitest';
import { advancedOn, setServerAdvanced, saveAdvanced } from '../advanced.js';
import { launcherHtml } from '../components/phone-shell.js';

describe('B11 (UX-23): Advanced follows the person everywhere', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div data-advanced-section="mgmt-sec-network" id="net-icon"></div>
      <div data-advanced-section="mgmt-sec-storage" id="storage-icon"></div>
      <button data-phone-open="vms" id="vms-tile"></button>
      <button data-phone-open="files" id="files-tile"></button>`;
  });

  it('the server setting hides the advanced icons and tiles, and only those', () => {
    setServerAdvanced(false);
    expect(advancedOn()).toBe(false);
    expect(document.getElementById('net-icon').style.display).toBe('none');
    expect(document.getElementById('storage-icon').style.display).toBe('');
    expect(document.getElementById('vms-tile').hidden).toBe(true);
    expect(document.getElementById('files-tile').hidden).toBe(false);
    setServerAdvanced(true);
    expect(document.getElementById('net-icon').style.display).toBe('');
    expect(document.getElementById('vms-tile').hidden).toBe(false);
  });

  it('the phone launcher leaves out advanced tiles while it is off', () => {
    setServerAdvanced(false);
    const div = document.createElement('div');
    div.innerHTML = launcherHtml();
    expect(div.querySelector('[data-phone-open="vms"]').hidden).toBe(true);
    expect(div.querySelector('[data-phone-open="files"]').hidden).toBe(false);
  });

  it('flipping the switch saves it to the account', async () => {
    const api = { put: vi.fn().mockResolvedValue({}) };
    await saveAdvanced(true, api);
    expect(api.put).toHaveBeenCalledWith('/api/auth/me/preferences', { advanced: true });
    expect(advancedOn()).toBe(true);
  });
});
