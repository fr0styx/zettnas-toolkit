import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api, setConfirmationHandler } from '../api.js';

const json = (status, body) => ({
  status,
  ok: status >= 200 && status < 300,
  headers: new Headers(),
  json: async () => body,
  clone() { return this; },
});

describe('destructive-action confirm flow (428)', () => {
  let calls;
  beforeEach(() => {
    calls = [];
    window.fetch = vi.fn(async (url, opts = {}) => {
      calls.push({ url, opts });
      if (url === '/api/confirmations') return json(200, { token: 'zcf_test' });
      if (opts.headers && opts.headers['X-Confirm-Token'] === 'zcf_test') return json(200, { status: 'ok' });
      return json(428, { error: 'confirmation_required', action: 'fs.trash.empty', target: '', summary: 'Empty the trash' });
    });
  });

  it('asks, fetches a token and retries', async () => {
    const ask = vi.fn(async () => true);
    setConfirmationHandler(ask);
    const res = await api.delete('/api/fs/trash/empty');
    expect(res.status).toBe('ok');
    expect(ask).toHaveBeenCalledWith(expect.objectContaining({ summary: 'Empty the trash' }));
    expect(JSON.parse(calls[1].opts.body)).toEqual({ action: 'fs.trash.empty', target: '' });
  });

  it('does not ask again when the caller already confirmed', async () => {
    const ask = vi.fn(async () => true);
    setConfirmationHandler(ask);
    await api.delete('/api/fs/trash/empty', { confirmed: true });
    expect(ask).not.toHaveBeenCalled();
    expect(calls.map((c) => c.url)).toEqual(['/api/fs/trash/empty', '/api/confirmations', '/api/fs/trash/empty']);
  });

  it('stops when the user cancels', async () => {
    setConfirmationHandler(async () => false);
    await expect(api.delete('/api/fs/trash/empty')).rejects.toMatchObject({ error: 'cancelled' });
    expect(calls).toHaveLength(1);
  });
});
