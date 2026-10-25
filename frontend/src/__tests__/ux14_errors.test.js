import { describe, it, expect } from 'vitest';
import { explain, nextStep } from '../error-text.js';
import { ApiError } from '../api.js';

const res = (status, body) => ({ status, statusText: 'x', json: async () => body });

describe('errors say what happened and what to do (UX-14)', () => {
  it('adds the next step to the server message', () => {
    expect(explain('Path is outside allowed folders.', 'forbidden')).toBe('Path is outside allowed folders. Ask the owner of this server if you need access.');
    expect(explain('Too many attempts', 'rate_limited')).toBe('Too many attempts. Wait a minute, then try again.');
    expect(explain('Bad name', 'validation_error')).toBe('Bad name');
    expect(explain('', 'not_found')).toContain('Refresh the page');
    expect(nextStep('internal_error', { reference: 'ab12cd34' })).toContain('ab12cd34');
    expect(nextStep('internal_error')).toContain('diagnostics bundle');
    expect(nextStep('timeout')).toContain('busy');
  });

  it('API errors carry it, with the server reference for a 500', async () => {
    const e = await ApiError.from(res(500, { error: 'internal_error', detail: 'Something went wrong on the server.', reference: 'deadbeef' }));
    expect(e.message).toContain('Something went wrong on the server.');
    expect(e.message).toContain('deadbeef');
    expect(e.error).toBe('internal_error');
    const c = await ApiError.from(res(409, { error: 'conflict', detail: 'A share named media exists' }));
    expect(c.message).toBe('A share named media exists. Choose another name, or refresh to see the current state.');
    const plain = await ApiError.from({ status: 502, statusText: 'Bad Gateway', json: async () => { throw new Error('html'); } });
    expect(plain.message).toBe('HTTP 502: Bad Gateway');
  });
});
