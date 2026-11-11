import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showDangerConfirm: vi.fn() }));
import { api } from '../api.js';
import * as toast from '../toast.js';
import { initUpsDrawerControls, renderUpsTelemetry } from '../components/management/ups.js';

beforeEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe('Power page refresh and badge (SET-15, Power B8 and B9)', () => {
  it('Refresh says the readings were refreshed, once, and never "saved"', async () => {
    document.body.innerHTML = '<button id="btn-refresh-ups">Refresh</button>';
    vi.spyOn(api, 'get').mockResolvedValue({});
    await initUpsDrawerControls();
    document.getElementById('btn-refresh-ups').click();
    await vi.waitFor(() => expect(toast.showToast).toHaveBeenCalled());
    const said = toast.showToast.mock.calls.map((c) => c[0]);
    expect(said).toContain('UPS readings refreshed.');
    expect(said).not.toContain('UPS settings saved');
  });

  it('the sidebar badge loses its red when the USB error is gone', () => {
    document.body.innerHTML = '<span id="mgmt-sidebar-ups-badge"></span>';
    renderUpsTelemetry({ available: false, permission_error: true, error_kind: 'usb_permission' });
    renderUpsTelemetry({ available: true, status: 'OL', battery_charge_pct: 90 });
    expect(document.getElementById('mgmt-sidebar-ups-badge').style.color).toBe('');
  });

  it('management.js no longer wires its own Refresh', async () => {
    const { readFileSync } = await import('node:fs');
    expect(readFileSync('frontend/src/components/management.js', 'utf8')).not.toContain("getElementById('btn-refresh-ups')");
  });
});
