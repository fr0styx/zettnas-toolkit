import { describe, it, expect } from 'vitest';
import { buildShareAccessHtml, collectShareAccess } from '../components/share-access.js';

describe('share access grid (SEC-10)', () => {
  it('renders shares x users and collects only explicit settings', () => {
    const root = document.createElement('div');
    root.innerHTML = buildShareAccessHtml(
      { default_level: 'read', shares: [{ name: 'media', path: '/mnt/user/media', default: 'write', users: { alice: 'none' } }, { name: 'docs', path: '/mnt/user/docs', users: {} }] },
      [{ username: 'Alice' }, { username: 'bob' }]
    );
    expect(root.querySelectorAll('select[data-share][data-user]')).toHaveLength(4);
    root.querySelector('select[data-share="docs"][data-user="bob"]').value = 'write';
    expect(collectShareAccess(root)).toEqual({
      default_level: 'read',
      shares: { media: { users: { alice: 'none' }, default: 'write' }, docs: { users: { bob: 'write' } } },
    });
  });

  it('escapes share names', () => {
    const root = document.createElement('div');
    root.innerHTML = buildShareAccessHtml({ shares: [{ name: '<img src=x onerror=alert(1)>', path: '/x', users: {} }] }, []);
    expect(root.querySelector('img')).toBeNull();
  });
});
