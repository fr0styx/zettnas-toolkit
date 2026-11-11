import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import en from '../locales/en.js';

describe('Power switches say what they do (SET-15, Power B7 and decision 6)', () => {
  it('the labels are true', () => {
    expect(en['mgmt.ups_chk_docker']).toMatch(/always stopped/);
    expect(en['mgmt.ups_chk_docker']).not.toMatch(/WAL|database/);
    expect(en['mgmt.ups_chk_cutpower']).not.toMatch(/load\.off\.delay/);
  });

  it('the sockets switch can be greyed with its reason, and the restart line is there', () => {
    const html = readFileSync('frontend/src/windows/management-window.html', 'utf8');
    expect(html).toContain('id="ups-cutpower-why"');
    expect(html).toContain('id="ups-restart-line"');
    const js = readFileSync('frontend/src/components/management/ups.js', 'utf8');
    expect(js).toMatch(/_pathBy === 'kiboto' && \/nut\/\.test\(_upsMode\)/);
  });
});
