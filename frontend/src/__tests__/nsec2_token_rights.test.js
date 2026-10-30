import { describe, it, expect } from 'vitest';
import { tokenRights, tokenRowHtml } from '../components/settings.js';

describe("each token's rights in the list (NSEC-2)", () => {
  it('names the kind it was made as', () => {
    expect(tokenRights(['files:read', 'shares:read'])).toBe('Read files');
    expect(tokenRights(['shares:read', 'files:read', 'shares:user_write', 'files:write'])).toBe('Read and change files');
    expect(tokenRights(['storage:read', 'system:view', 'hardware:read'])).toBe('See how the server is doing (monitoring)');
    expect(tokenRights(['*'])).toContain('Everything');
    expect(tokenRights(['files:read'])).toBe('1 chosen right');
    expect(tokenRights([])).toBe('0 chosen rights');
  });

  it('shows it in the row, with the rights themselves on hover', () => {
    const html = tokenRowHtml({ id: 't1', name: 'Backup tool', masked_token: 'zat_…', scopes: ['shares:read', 'files:read'] });
    expect(html).toContain('May: Read files');
    expect(html).toContain('title="shares:read, files:read"');
  });
});
