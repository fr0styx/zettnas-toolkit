// SET-10: the password form acts on the signed-in person, for every role.
import { describe, it, expect, vi } from 'vitest';
import { api } from '../api.js';
import { changeOwnPassword } from '../components/own-password.js';

describe('changing your own password', () => {
  it.each([['superadmin'], ['share_user'], ['kid']])('uses the per-account route for a %s', async (role) => {
    vi.spyOn(api, 'get').mockResolvedValue({ id: 'usr 1', role });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok' });
    await changeOwnPassword('old', 'new password 1');
    expect(post).toHaveBeenCalledWith('/api/users/usr%201/password', { current_password: 'old', new_password: 'new password 1' });
  });

  it('does nothing when nobody is signed in', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    const post = vi.spyOn(api, 'post');
    post.mockClear();
    await expect(changeOwnPassword('a', 'b')).rejects.toThrow('Not signed in.');
    expect(post).not.toHaveBeenCalled();
  });
});
