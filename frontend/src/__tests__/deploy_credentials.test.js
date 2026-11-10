/** After a deploy: the sign-in details, and where a generated password is kept. */
import { describe, it, expect } from 'vitest';
import { showDeployCredentials } from '../components/management/docker.js';

function box() {
  const wrap = document.createElement('div');
  const success = document.createElement('div');
  wrap.append(success);
  return { wrap, success };
}

describe('deploy credentials', () => {
  it('show the login and say a generated password is kept in a hidden file', () => {
    const { wrap, success } = box();
    showDeployCredentials(success, { credentials: { user: 'backup', password: 'x'.repeat(24), note: 'Use it on your own network.' } }, 'nas:8000');
    const text = wrap.querySelector('.adm-credentials').textContent;
    expect(text).toContain('backup');
    expect(text).toContain('Use it on your own network.');
    expect(text).toContain('Saved in a hidden file');
  });

  it('say nothing of a file for a short password, and show the address for an app without a web page', () => {
    const { wrap, success } = box();
    showDeployCredentials(success, { has_webui: false, credentials: { password: 'short' } }, 'nas:5432');
    const text = wrap.querySelector('.adm-credentials').textContent;
    expect(text).toContain('nas:5432');
    expect(text).not.toContain('Saved in a hidden file');
    showDeployCredentials(success, { credentials: {} }, 'nas:1');
    expect(wrap.querySelector('.adm-credentials')).toBeNull();
  });
});
