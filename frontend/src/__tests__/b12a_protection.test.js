import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
const { api } = await import('../api.js');
const { jobsHtml, installProtectionJobs } = await import('../components/management/protection.js');

const JOBS = [
  { kind: 'backup', id: 'b1', name: 'Photos to USB', status: 'ok', why: '', last_ok: 1700000000 },
  { kind: 'scrub', id: 'tank', name: 'tank', status: 'off', why: 'off: a scrub spins up the pool', enabled: false },
  { kind: 'scrub', id: 'array', name: 'Array', status: 'host_owned', why: 'Unraid runs its own checks' },
];

describe('B12a (REL-12): what protects your data', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="m"></div>';
  });

  it('lists every job with its state, and a switch only where ZettNAS runs the check', () => {
    const div = document.createElement('div');
    div.innerHTML = String(jobsHtml(JOBS));
    expect(div.textContent).toContain('Photos to USB');
    expect(div.textContent).toContain('Run by the host');
    expect(div.querySelectorAll('[data-scrub-pool]')).toHaveLength(1);
    expect(div.querySelector('[data-scrub-pool="tank"]').checked).toBe(false);
  });

  it('switching the check on asks the server, which asks to confirm', async () => {
    api.get.mockResolvedValue({ jobs: JOBS });
    api.put.mockResolvedValue({});
    await installProtectionJobs(document.getElementById('m'));
    const sw = document.querySelector('[data-scrub-pool="tank"]');
    sw.checked = true;
    sw.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/protection/scrub/tank', { enabled: true }));
  });

  it('a cancelled confirmation puts the switch back quietly', async () => {
    api.get.mockResolvedValue({ jobs: JOBS });
    api.put.mockRejectedValue(Object.assign(new Error('cancelled'), { error: 'cancelled' }));
    await installProtectionJobs(document.getElementById('m'));
    const sw = document.querySelector('[data-scrub-pool="tank"]');
    sw.checked = true;
    sw.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(sw.checked).toBe(false));
  });
});
