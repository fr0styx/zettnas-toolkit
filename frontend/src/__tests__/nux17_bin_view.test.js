import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../i18n.js', () => ({
  t: (key, fallback, params = {}) => String(fallback).replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m)),
}));
const confirm = vi.fn();
vi.mock('../toast.js', () => ({ showConfirmToast: (...a) => confirm(...a), showToast: vi.fn() }));
vi.mock('../api.js', () => ({ api: { delete: vi.fn(async () => ({})) } }));
let user = { scopes: ['*'] };
vi.mock('../components/session.js', () => ({ getCurrentUser: () => user }));

const { binColumns, binBar, mayEmpty } = await import('../components/fm-bin-view.js');

function fakeFm() {
  const windowEl = document.createElement('div');
  windowEl.innerHTML = '<div class="fm-header-row"><div class="fm-col-type">Type <span></span></div><div class="fm-col-mtime">Modified <span></span></div></div>';
  return { windowEl, colType: windowEl.querySelector('.fm-col-type'), colMtime: windowEl.querySelector('.fm-col-mtime') };
}

describe('Recycle Bin view (NUX-17)', () => {
  beforeEach(() => confirm.mockClear());

  it('renames the columns in the bin and back outside it', () => {
    const fm = fakeFm();
    binColumns(fm, true);
    expect(fm.colType.textContent.trim()).toBe('From');
    expect(fm.colMtime.textContent.trim()).toBe('Deleted');
    expect(fm.colMtime.querySelector('span')).not.toBeNull(); // the sort icon stays
    binColumns(fm, false);
    expect(fm.colMtime.textContent.trim()).toBe('Modified');
  });

  it('shows how long items stay and asks for a typed word to empty everything', () => {
    const fm = fakeFm();
    const bar = binBar(fm, true, () => {});
    expect(bar.textContent).toContain('30 days');
    bar.querySelector('.fm-bin-empty').click();
    const [, msg, , , options] = confirm.mock.calls[0];
    expect(msg).toContain('every share');
    expect(options).toMatchObject({ destructive: true, typeToConfirm: 'EMPTY' });
    binBar(fm, false, () => {});
    expect(fm.windowEl.querySelector('.fm-bin-bar').hidden).toBe(true);
  });

  it('shows Empty only to people who may empty the bins', async () => {
    user = { scopes: ['shares:read'] };
    expect(mayEmpty(user)).toBe(false);
    let bar = binBar(fakeFm(), true, () => {});
    await bar.ready;
    expect(bar.querySelector('.fm-bin-empty').hidden).toBe(true);
    user = { scopes: ['storage:admin'] };
    expect(mayEmpty(user)).toBe(true);
    bar = binBar(fakeFm(), true, () => {});
    await bar.ready;
    expect(bar.querySelector('.fm-bin-empty').hidden).toBe(false);
    expect(mayEmpty(null)).toBe(false);
  });
});
