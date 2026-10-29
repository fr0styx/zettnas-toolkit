import { describe, it, expect } from 'vitest';
import fs from 'fs';
import path from 'path';
import { binConfirmText } from '../components/file-manager.js';

describe('file manager delete prompts and counts', () => {
  it('names the file when one is selected', () => {
    expect(binConfirmText(['/mnt/user/Media/Photos/IMG_0412.HEIC'])).toBe('Move “IMG_0412.HEIC” to the Recycle Bin?');
    expect(binConfirmText(['/mnt/user/Media/Photos/2021/'])).toBe('Move “2021” to the Recycle Bin?');
  });

  it('counts several, with the plural filled in', () => {
    expect(binConfirmText(['/mnt/user/a', '/mnt/user/b'])).toBe('Move 2 items to the Recycle Bin?');
  });

  it('says a delete inside the Recycle Bin is for good', () => {
    expect(binConfirmText(['/mnt/user/.RecycleBin/old.txt'])).toBe("“old.txt” will be deleted for good. This can't be undone.");
    expect(binConfirmText(['/mnt/user/.RecycleBin/a', '/mnt/user/.RecycleBin/b'])).toContain('2 items will be deleted for good');
    expect(binConfirmText(['/mnt/user/.RecycleBin/a', '/mnt/user/b'])).toBe('Move 2 items to the Recycle Bin?');
  });

  it('never patches a count into a translated string by text replace', () => {
    // t(...).replace('{count}', n) leaves "{count, plural, ...}" on screen once the string is a plural
    const src = fs.readFileSync(path.resolve(__dirname, '../components/file-manager.js'), 'utf8');
    expect(src).not.toMatch(/\)\.replace\('\{count\}'/);
  });
});
