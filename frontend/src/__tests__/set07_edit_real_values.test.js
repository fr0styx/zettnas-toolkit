/** SET-07: the app's Edit tab always starts from the real values. */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const src = readFileSync(resolve(__dirname, '..', 'components/container-modal.js'), 'utf8');
const edit = src.slice(src.indexOf('async function renderContainerEditTab(cid) {'), src.indexOf('const portsList = (details.ports || [])'));

describe('the Edit tab of an app (SET-07)', () => {
  it('asks for the real values every time, and never reuses the Overview’s hidden ones', () => {
    expect(edit).toContain('/details?unmask=true');
    expect(edit).not.toContain('_activeDetails');
    expect(edit).not.toMatch(/if \(!_activeDetails/);
  });

  it('shows an error, not a form, when they cannot be loaded', () => {
    const fail = edit.slice(edit.indexOf('} catch (e) {'));
    expect(fail).toContain("t('ci.load_failed'");
    expect(fail).toContain('return;');
  });
});
