import { describe, it, expect, beforeEach } from 'vitest';
import { showToast } from '../toast.js';

describe('Toast headings', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('calls an ordinary failure an error and announces it', () => {
    showToast('Could not rename the file.', 'error');
    const item = document.querySelector('.top-toast-item');
    expect(item).not.toBeNull();
    expect(item.textContent).toContain('Error');
    expect(item.textContent).not.toContain('Security alert');
    expect(item.getAttribute('role')).toBe('alert');
    expect(item.querySelector('.top-toast-close').getAttribute('aria-label')).toBe('Dismiss');
  });

  it('keeps security wording for security events', () => {
    showToast('Blocked a sign-in from a new address.', 'security');
    expect(document.querySelector('.top-toast-item').textContent).toContain('Security alert');
  });
});
