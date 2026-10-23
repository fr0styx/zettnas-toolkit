import { describe, it, expect } from 'vitest';
import { _formatChatMarkdown } from '../components/management.js';

describe('chat citation chips', () => {
  const citations = [{ path: '/mnt/pool/docs/msa.pdf', name: 'msa.pdf' }];

  it('turns a document citation into a chip that opens the file', () => {
    const html = _formatChatMarkdown('Net 30 terms [Doc 1].', { citations, webSources: [] });
    expect(html).toContain('data-action="open-file-preview"');
    expect(html).toContain('data-path="/mnt/pool/docs/msa.pdf"');
    expect(html).toContain('[1]</button>');
  });

  it('drops citations that point at no source', () => {
    const html = _formatChatMarkdown('Paid late [4].', { citations, webSources: [] });
    expect(html).not.toContain('[4]');
  });

  it('links web citations to the page', () => {
    const html = _formatChatMarkdown('Released in May [1].', { citations, webSources: [{ url: 'https://example.com/a', title: 'A' }] });
    expect(html).toContain('href="https://example.com/a"');
  });
});
