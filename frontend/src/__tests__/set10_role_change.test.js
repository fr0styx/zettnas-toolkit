// SET-10: a kid or a guest can be edited. The dialog shows their role, and sends the role only
// when it was changed.
import { describe, it, expect } from 'vitest';
import { roleChange, showRole } from '../components/role-change.js';

describe('the role in the Edit dialog', () => {
  it('sends no role unless another one was chosen', () => {
    expect(roleChange('kid', 'kid')).toEqual({});
    expect(roleChange('', 'kid')).toEqual({}); // the blank field that blocked every edit
    expect(roleChange(undefined, 'kid')).toEqual({});
    expect(roleChange('share_user', 'kid')).toEqual({ role_id: 'share_user' });
  });

  it('shows a role the list offers, and adds one it does not', () => {
    const select = document.createElement('select');
    select.innerHTML = '<option value="share_user">Family member</option><option value="kid">Kid</option>';
    showRole(select, 'kid');
    expect(select.value).toBe('kid');
    expect(select.options).toHaveLength(2);
    showRole(select, 'house_guest', 'House guest');
    expect(select.value).toBe('house_guest');
    expect(select.options[2].textContent).toBe('House guest');
    showRole(null, 'kid');
    showRole(select, '');
    expect(select.value).toBe('house_guest');
  });

  it('both role lists of the page offer Kid and Guest', async () => {
    const { readFileSync } = await import('node:fs');
    const html = readFileSync('frontend/index.html', 'utf8');
    for (const id of ['add-user-role', 'edit-user-role']) {
      const list = html.slice(html.indexOf(`id="${id}"`), html.indexOf('</select>', html.indexOf(`id="${id}"`)));
      for (const role of ['share_user', 'kid', 'guest', 'app_operator', 'storage_admin', 'backup_operator', 'auditor', 'superadmin']) {
        expect(list, `${id} lacks ${role}`).toContain(`value="${role}"`);
      }
    }
  });
});
