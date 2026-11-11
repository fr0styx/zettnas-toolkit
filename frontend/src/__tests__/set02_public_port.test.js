import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../components/management/funnel-steps.js', () => ({ funnelStepsHtml: () => '', recheckWhileOpen: vi.fn() }));

const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { renderPublicLinks } = await import('../components/management/public-links.js');

const flush = () => new Promise((r) => setTimeout(r, 0));
const BASE = { tailscale: true, enabled: true, live: true, base_url: 'https://nas.example:8443', funnel: {}, port_public: true, also_public: [] };

describe('the share links card warns when the port carries more (SET-02)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <div id="pl-card"><button id="pl-toggle"></button><div id="pl-status"></div><a id="pl-approve" hidden></a></div>`;
  });

  it('shows nothing extra when only the share links are public', () => {
    renderPublicLinks(BASE);
    expect(document.getElementById('pl-port-alert')).toBeNull();
  });

  it('says what else is on the internet, with an icon, a word and a way out', async () => {
    renderPublicLinks({ ...BASE, also_public: ['/'] });
    const alert = document.getElementById('pl-port-alert');
    expect(alert.getAttribute('role')).toBe('alert');
    expect(alert.hidden).toBe(false);
    expect(alert.textContent).toContain('⚠ Problem:');
    expect(alert.textContent).toContain('also serves /');
    api.post.mockResolvedValue({ ...BASE, enabled: false, live: false, port_public: false, also_public: [] });
    alert.querySelector('button').click();
    await flush();
    expect(api.post).toHaveBeenCalledWith('/api/network/public-links/close-port');
    expect(document.getElementById('pl-port-alert').hidden).toBe(true);
    expect(document.getElementById('pl-toggle').getAttribute('aria-pressed')).toBe('false');
  });

  it('keeps the alert and says why when taking it off failed', async () => {
    renderPublicLinks({ ...BASE, enabled: false, live: false, also_public: ['/'] });
    api.post.mockRejectedValue(new Error('Tailscale did not answer'));
    const btn = document.querySelector('#pl-port-alert button');
    btn.click();
    await flush();
    expect(showToast).toHaveBeenCalledWith('Tailscale did not answer', 'error');
    expect(btn.disabled).toBe(false);
    expect(document.getElementById('pl-port-alert').hidden).toBe(false);
  });

  it('does not warn about a port that is only served inside the tailnet', () => {
    renderPublicLinks({ ...BASE, enabled: false, live: false, port_public: false, also_public: ['/'] });
    expect(document.getElementById('pl-port-alert')).toBeNull();
  });
});
