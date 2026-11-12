/** Network report F1: someone who may only look sees the state, not a form the server refuses. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('qrcode', () => ({ default: { toString: vi.fn(async (text) => `<svg data-text="${text}"></svg>`) } }));
const { ZettEventBus } = await import('../event-bus.js');
await import('../route-access.js');
const ra = await import('../components/remote-access.js');

const RUNNING = { state: 'Running', name: 'nas.tail1.ts.net', ips: ['100.64.0.2'], https: true, addresses: { kiboto: 'https://nas.tail1.ts.net/' } };
const viewer = { username: 'auditor', scopes: ['system:view', '*:read'] };

describe('Away from home for someone who may only look', () => {
  beforeEach(() => ZettEventBus.emit('session:user', viewer));
  afterEach(() => ZettEventBus.emit('session:user', null));

  it('shows the connection without its buttons, and a note', async () => {
    const body = await ra.remoteBody(RUNNING);
    expect(body.textContent).toContain('nas.tail1.ts.net');
    expect(body.querySelector('[data-remote]')).toBeNull();
    expect(body.querySelector('.state-block.is-readonly')).not.toBeNull();
  });

  it('shows a note instead of the connect form', async () => {
    const body = await ra.remoteBody({ state: 'Stopped' });
    expect(body.matches('.state-block.is-readonly')).toBe(true);
    expect(body.textContent).toBe('Only someone who may change settings can connect this NAS.');
  });

  it('a NetBird connection loses its Disconnect too', async () => {
    const body = await ra.remoteBody({ state: 'NotInstalled' }, { state: 'Connected', ip: '100.92.0.1', name: 'nas' });
    expect(body.querySelector('[data-netbird]')).toBeNull();
  });

  it('who may change settings keeps everything', () => {
    expect(ra.mayChange({ scopes: ['system:config'] })).toBe(true);
    expect(ra.mayChange({ scopes: ['*'] })).toBe(true);
    expect(ra.mayChange(viewer)).toBe(false);
    expect(ra.mayChange(null)).toBe(true);
  });
});
