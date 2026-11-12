/** Network report F3: the Network page's dialogs work with a keyboard. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showActionToast: vi.fn(), showPromptToast: vi.fn() }));
const net = await import('../components/management/network.js');
const { showNetDialog, hideNetDialog } = await import('../components/management/net-dialog.js');

const DIALOG = `
  <button id="opener">Create network</button>
  <div id="network-docker-create-overlay" style="display:none">
    <div class="smart-modal-window">
      <input id="net-docker-name-input"><input id="net-docker-subnet-input"><input id="net-docker-gateway-input">
      <button id="last">Create</button>
    </div>
  </div>`;

const key = (el, k, shift = false) => el.dispatchEvent(new KeyboardEvent('keydown', { key: k, shiftKey: shift, bubbles: true }));

describe('Network dialogs with a keyboard', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('focus goes in, Escape closes, focus comes back', () => {
    document.body.innerHTML = DIALOG;
    const opener = document.getElementById('opener');
    opener.focus();
    net.openDockerNetworkCreateModal();
    const overlay = document.getElementById('network-docker-create-overlay');
    expect(overlay.style.display).toBe('flex');
    expect(document.activeElement.id).toBe('net-docker-name-input');
    const last = document.getElementById('last');
    last.focus();
    key(last, 'Tab');
    expect(document.activeElement.id).toBe('net-docker-name-input'); // Tab stays inside
    key(last, 'Escape');
    expect(overlay.style.display).toBe('none');
    expect(document.activeElement).toBe(opener);
  });

  it('opening twice keeps one trap; closing a dialog that was never opened is harmless', () => {
    document.body.innerHTML = DIALOG;
    const overlay = document.getElementById('network-docker-create-overlay');
    const close = vi.fn(() => hideNetDialog(overlay));
    showNetDialog(overlay, close);
    showNetDialog(overlay, close);
    key(document.getElementById('last'), 'Escape');
    expect(close).toHaveBeenCalledTimes(1);
    hideNetDialog(overlay);
    hideNetDialog(null);
    const bare = document.createElement('div');
    document.body.append(bare);
    showNetDialog(bare, () => {});
    expect(document.activeElement).toBe(bare);
    hideNetDialog(bare);
  });
});
