import { describe, it, expect } from 'vitest';
import { tokenRowHtml, parseTokenFolders, mcpSnippets } from '../components/settings.js';

describe('API tokens: folders, use and client settings (COMP-06)', () => {
  it('shows the folders a token is limited to, or that it has them all', () => {
    const limited = tokenRowHtml({ id: 'a', name: 'Paperless', masked_token: 'zat_ab...cd', folders: ['/mnt/user/Docs'] });
    expect(limited).toContain('/mnt/user/Docs');
    expect(limited).toContain('zn-tag');
    expect(tokenRowHtml({ id: 'b', name: 'HA', masked_token: 'zat_x', folders: [] })).toContain('All folders');
  });

  it('says when, from where and by which client a token was last used', () => {
    const html = tokenRowHtml({ id: 'c', name: 'Cursor', masked_token: 'zat_x', last_used_at: 1761700000, last_used_ip: '10.0.0.5', last_client: 'Cursor 1.4' });
    expect(html).toContain('Last used');
    expect(html).toContain('from 10.0.0.5');
    expect(html).toContain('by Cursor 1.4');
    expect(tokenRowHtml({ id: 'd', name: 'New', masked_token: 'zat_x' })).toContain('Never used');
  });

  it('escapes what the server sends', () => {
    const html = tokenRowHtml({ id: 'e', name: '<img src=x>', masked_token: 'zat_x', folders: ['/a<b>'], last_used_at: 1, last_client: '<script>' });
    expect(html).not.toContain('<img');
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<b>');
  });

  it('reads folders one per line or separated by commas', () => {
    expect(parseTokenFolders('/mnt/user/Docs\n /mnt/user/Tax , \n')).toEqual(['/mnt/user/Docs', '/mnt/user/Tax']);
    expect(parseTokenFolders('')).toEqual([]);
  });

  it('fills the client settings with this server and the new token', () => {
    const parts = mcpSnippets('https://nas.example', 'zat_TOKEN');
    expect(parts.map((p) => p.id)).toEqual(['claude-code', 'cursor', 'desktop']);
    expect(parts[0].text).toBe('claude mcp add --transport http zettnas https://nas.example/api/mcp --header "Authorization: Bearer zat_TOKEN"');
    const cursor = JSON.parse(parts[1].text);
    expect(cursor.mcpServers.zettnas).toEqual({ url: 'https://nas.example/api/mcp', headers: { Authorization: 'Bearer zat_TOKEN' } });
    const desktop = JSON.parse(parts[2].text);
    expect(desktop.mcpServers.zettnas.args).toEqual(['mcp-remote', 'https://nas.example/api/mcp', '--header', 'Authorization: Bearer zat_TOKEN']);
  });
});
