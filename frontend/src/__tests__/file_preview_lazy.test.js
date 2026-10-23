import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'fs';
import path from 'path';

const open = vi.fn();
vi.mock('../components/file-preview-modal.js', () => ({ openFilePreviewModal: open }));

describe('file viewer loads on first use (PERF-5)', () => {
  it('is not imported by the file manager or the page', () => {
    for (const f of ['../main.js', '../components/file-manager.js', '../components/file-manager-helpers.js']) {
      const src = readFileSync(path.resolve(__dirname, f), 'utf8');
      expect(src).not.toMatch(/^import .*file-preview-modal\.js/m);
    }
  });

  it('the global opens the viewer before it has loaded', async () => {
    delete window.openFilePreviewModal;
    await import('../file-preview-loader.js');
    expect(typeof window.openFilePreviewModal).toBe('function');
    await window.openFilePreviewModal('/mnt/user/a.pdf', 'a.pdf');
    expect(open).toHaveBeenCalledWith('/mnt/user/a.pdf', 'a.pdf');
  });
});
