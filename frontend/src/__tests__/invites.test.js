import { describe, it, expect } from 'vitest';
import { invitesHtml, inviteTokenFromHash } from '../components/invites.js';

describe('invite links (Batch 6)', () => {
  it('reads the token from the link', () => {
    expect(inviteTokenFromHash('#/invite/abcDEF_123-xyz7890abcd')).toBe('abcDEF_123-xyz7890abcd');
    expect(inviteTokenFromHash('#/apps')).toBe(null);
    expect(inviteTokenFromHash('#/invite/short')).toBe(null);
  });

  it('lists invites with their state and offers the family roles', () => {
    document.body.innerHTML = invitesHtml([
      { id: 'a1', role_id: 'kid', note: 'Max', uses: 0, max_uses: 1, expires_at: 2000000000, active: true },
      { id: 'b2', role_id: 'guest', note: '', uses: 1, max_uses: 1, expires_at: 2000000000, active: false },
    ]);
    expect(document.querySelectorAll('[data-invite-revoke]').length).toBe(1);
    expect(document.querySelector('.invite-row.is-used')).not.toBeNull();
    expect([...document.querySelectorAll('select[name=role_id] option')].map((o) => o.value)).toEqual(['share_user', 'kid', 'guest']);
  });
});
