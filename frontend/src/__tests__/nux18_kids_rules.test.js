// NUX-18: kids' rules in one place
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
import { api } from '../api.js';
import { hoursText, aiSwitchesHtml, kidsRulesHtml, renderKidsRules } from '../components/kids-rules.js';

const NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const USERS = [
  { id: 1, username: 'mum', role_id: 'superadmin' },
  { id: 2, username: 'ana', display_name: 'Ana', role_id: 'kid', signin_hours: { days: [0, 1, 2, 3, 4], start: '07:00', end: '20:00' } },
  { id: 3, username: 'visitor', role_id: 'guest' },
];
const ACCESS = { roles: [{ id: 'superadmin', on: true, locked: true }, { id: 'kid', on: false, search: true }, { id: 'guest', on: false, search: false }] };
const FILTER = { people: { ana: { devices: ['192.168.1.20', 'aa:bb:cc:dd:ee:ff'] } } };

describe('hoursText', () => {
  it('names a run of days, every day, single days and no limit', () => {
    expect(hoursText({ days: [0, 1, 2, 3, 4], start: '07:00', end: '20:00' }, NAMES)).toBe('Mon–Fri 07:00–20:00');
    expect(hoursText({ days: [0, 1, 2, 3, 4, 5, 6], start: '08:00', end: '21:00' }, NAMES)).toBe('Every day 08:00–21:00');
    expect(hoursText({ days: [5, 0], start: '09:00', end: '12:00' }, NAMES)).toBe('Mon, Sat 09:00–12:00');
    expect(hoursText(null, NAMES)).toBe('Any time');
  });
});

describe('kidsRulesHtml', () => {
  it('lists only kid and guest accounts, with hours and filtered devices', () => {
    const box = document.createElement('div');
    box.innerHTML = String(kidsRulesHtml(USERS, ACCESS, FILTER));
    const rows = box.querySelectorAll('tr[data-kid]');
    expect([...rows].map((r) => r.dataset.kid)).toEqual(['2', '3']);
    expect(rows[0].textContent).toContain('Ana');
    expect(rows[0].textContent).toContain('2 devices filtered');
    expect(rows[1].textContent).toContain('Any time');
    expect(rows[1].textContent).toContain('Not filtered');
  });

  it('leaves out device filtering and the AI switches the viewer cannot see', () => {
    const box = document.createElement('div');
    box.innerHTML = String(kidsRulesHtml(USERS, null, null));
    expect(box.querySelector('[data-kids-filter]')).toBeNull();
    expect(box.querySelector('[data-kids-ai]')).toBeNull();
    expect(box.querySelector('tr[data-kid="2"]').textContent).toContain('—');
  });

  it('says what to do without kid accounts', () => {
    const box = document.createElement('div');
    box.innerHTML = String(kidsRulesHtml([USERS[0]], ACCESS, FILTER));
    expect(box.querySelector('table')).toBeNull();
    expect(box.textContent).toContain('Kid role');
  });

  it('switches only the kid and guest roles', () => {
    const box = document.createElement('div');
    box.innerHTML = String(aiSwitchesHtml(ACCESS));
    const sw = [...box.querySelectorAll('[data-kids-ai]')];
    expect(sw.map((s) => `${s.dataset.role}:${s.dataset.kidsAi}:${s.checked}`)).toEqual([
      'kid:roles:false', 'kid:search_roles:true', 'guest:roles:false', 'guest:search_roles:false',
    ]);
    expect(aiSwitchesHtml({ roles: [{ id: 'superadmin', on: true }] })).toBeNull();
  });
});

describe('renderKidsRules', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.put.mockReset();
    api.get.mockImplementation((url) => Promise.resolve(url === '/api/ai/access' ? ACCESS : FILTER));
  });

  it('opens the person, the shared folders and the filter from its buttons', async () => {
    const mount = document.createElement('div');
    const ff = document.createElement('h4');
    ff.id = 'ff-title';
    ff.scrollIntoView = vi.fn();
    document.body.append(mount, ff);
    const onEdit = vi.fn();
    const onShares = vi.fn();
    await renderKidsRules(mount, USERS, { onEdit, onShares });
    mount.querySelector('[data-kids-edit="2"]').click();
    expect(onEdit).toHaveBeenCalledWith('2');
    mount.querySelector('[data-kids-shares]').click();
    expect(onShares).toHaveBeenCalled();
    mount.querySelector('[data-kids-filter]').click();
    expect(ff.scrollIntoView).toHaveBeenCalled();
    mount.remove();
    ff.remove();
  });

  it('saves a switch, and turns it back when saving fails', async () => {
    const mount = document.createElement('div');
    await renderKidsRules(mount, USERS, {});
    const ask = mount.querySelector('[data-kids-ai="roles"][data-role="kid"]');
    api.put.mockResolvedValueOnce({});
    ask.checked = true;
    ask.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(ask.disabled).toBe(false));
    expect(api.put).toHaveBeenCalledWith('/api/ai/access', { roles: { kid: true } });
    expect(ask.checked).toBe(true);
    api.put.mockRejectedValueOnce(new Error('no'));
    ask.checked = false;
    ask.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(ask.disabled).toBe(false));
    expect(ask.checked).toBe(true);
  });

  it('still shows the accounts when the other lists fail to load', async () => {
    api.get.mockRejectedValue(new Error('403'));
    const mount = document.createElement('div');
    await renderKidsRules(mount, USERS, {});
    expect(mount.querySelectorAll('tr[data-kid]').length).toBe(2);
    await renderKidsRules(null, USERS, {}); // no mount: nothing to do
  });
});
