import { describe, it, expect, vi } from 'vitest';

vi.mock('../i18n.js', () => ({
  t: (key, fallback, params = {}) => String(fallback).replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m)),
}));

const { confirmTextFor } = await import('../confirm-text.js');

describe('confirmTextFor (NUX-2)', () => {
  it('asks a known action as a question, with its target, red when it deletes', () => {
    const out = confirmTextFor({ action: 'share.delete', target: 'photos', summary: 'Delete share photos' });
    expect(out.title).toBe('Delete the share');
    expect(out.msg).toBe('Delete the share photos?');
    expect(out.options).toMatchObject({ destructive: true, okText: 'Delete the share', allowHtml: false });
  });

  it('keeps waking a drive blue', () => {
    expect(confirmTextFor({ action: 'disk.wake', target: 'sdb' }).options.destructive).toBe(false);
  });

  it('falls back to the server summary for an action it does not know', () => {
    const out = confirmTextFor({ action: 'new.thing', summary: 'Do the new thing' });
    expect(out.title).toBe('Confirm action');
    expect(out.msg).toBe('Do the new thing?');
    expect(confirmTextFor({}).msg).toBe("This can't be undone. Continue?");
  });
});
