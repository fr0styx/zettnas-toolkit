import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { emptyStateHtml, emptyRowHtml } from '../components/empty-state.js';
import { shareProtocolTags } from '../components/chassis-visualizer.js';

describe('empty states (UX-11)', () => {
  it('says what the place is for and offers the next step', () => {
    document.body.innerHTML = emptyStateHtml({ title: 'No <b>shares</b>', body: 'A share is…', action: { target: 'btn-x', label: 'Create share' } });
    const el = document.querySelector('.empty-state');
    expect(el.getAttribute('role')).toBe('status');
    expect(el.querySelector('.empty-state-title').textContent).toBe('No <b>shares</b>');
    const btn = el.querySelector('.empty-state-action');
    expect(btn.dataset.action).toBe('click-target');
    expect(btn.dataset.target).toBe('btn-x');
  });

  it('fits a table', () => {
    document.body.innerHTML = `<table><tbody>${emptyRowHtml(7, { title: 'Only you so far' })}</tbody></table>`;
    expect(document.querySelector('td').getAttribute('colspan')).toBe('7');
  });
});

describe('share protocol tags show the live service state', () => {
  const share = { export_smb: true, export_nfs: false };
  it('flags a protocol whose service is down', () => {
    const html = shareProtocolTags(share, { smb: { running: false }, webdav: { running: false, enabled: true }, sftp: { running: true, port: 2222 } });
    document.body.innerHTML = html;
    const tags = [...document.querySelectorAll('.proto-tag')].map((t) => [t.textContent, t.className.split(' ')[1]]);
    expect(tags).toEqual([['SMB', 'proto-down'], ['NFS', 'proto-off'], ['WebDAV', 'proto-down'], ['SFTP :2222', 'proto-on']]);
  });
  it('does not claim WebDAV or SFTP when it does not know', () => {
    document.body.innerHTML = shareProtocolTags(share, {});
    expect(document.body.textContent).not.toContain('WebDAV');
    expect(document.body.textContent).not.toContain('SFTP');
  });
});

describe('disabled buttons say why', () => {
  it('every conditionally disabled button carries a title', () => {
    const root = join(__dirname, '..', 'components');
    const files = [];
    const walk = (d) => readdirSync(d).forEach((f) => {
      const p = join(d, f);
      if (statSync(p).isDirectory()) walk(p);
      else if (f.endsWith('.js')) files.push(p);
    });
    walk(root);
    const bad = [];
    for (const f of files) {
      const src = readFileSync(f, 'utf8');
      for (const m of src.matchAll(/<button\b[^>]*\$\{[^}]*'disabled'[^}]*\}[^>]*>/g)) {
        if (!/title=/.test(m[0])) bad.push(`${f.split('components')[1]}: ${m[0].slice(0, 80)}`);
      }
    }
    expect(bad).toEqual([]);
  });
});
