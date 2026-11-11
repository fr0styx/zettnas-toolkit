// SET-13: the Event Log, the bell, the bell's preview and the entry dialog draw an entry the same
// way, in the reader's language, and an entry leads to the page the server named.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { setLanguage } from '../i18n.js';
import { ZettEventBus } from '../event-bus.js';
import { state } from '../state.js';
import { agoText, eventPlace, eventView, eventWhen, needsALook, repeatedText } from '../event-view.js';
import { ROUTES } from '../router.js';

vi.mock('../api.js', async (orig) => {
  const real = await orig();
  return { ...real, api: { ...real.api, put: vi.fn().mockResolvedValue({}), get: vi.fn().mockResolvedValue({}) } };
});
const { api } = await import('../api.js');
const bell = await import('../components/dock/notifications.js');
const { renderEventLog, initEvents } = await import('../components/events.js');

const POWER = { id: 7, ts: 1791394000, level: 'info', title: 'Power is back', message: 'Mains power returned after 40 s.', kind: 'ups_power_back', link: 'power', details: { title_key: 'ev.ups_power_back.title', msg_key: 'ev.ups_power_back.msg', params: { secs: 40, charge: 97 } } };
const BACKUP = { id: 8, ts: 1791394100, level: 'error', title: 'Backup failed: Photos', message: "Backup job 'Photos' failed: disk full", kind: 'backup_failed', link: 'backup', details: { title_key: 'alert.backup_failed.title', msg_key: 'alert.backup_failed.msg', params: { name: 'Photos', error: 'disk full' } } };
const BLOCKED = { id: 9, ts: 1791394200, last_ts: 1791394800, count: 3, level: 'warning', title: 'Address blocked', message: '10.0.0.7 after 5 wrong passwords' };

describe('one view of an entry', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('gives the look, the word for the level and the text in the reader’s language', async () => {
    expect(eventView(BACKUP)).toMatchObject({ look: 'error', icon: '❌', word: 'Problem', title: 'Backup failed: Photos' });
    expect(eventView({ level: 'critical', title: 'x', message: 'y' }).look).toBe('error');
    expect(eventView(POWER).word).toBe('Information');
    expect(eventView({ level: 'success', title: 'x', message: 'y' }).word).toBe('Done');
    expect(eventView(null)).toMatchObject({ look: 'info', title: '', message: '', when: 0, repeated: '' });
    await setLanguage('de');
    expect(eventView(BACKUP).title).toBe('Sicherung fehlgeschlagen: Photos');
    expect(eventView(BACKUP).word).toBe('Problem');
    expect(eventView(BLOCKED).title).toBe('Address blocked'); // no key: the text as the server wrote it
  });

  it('a repeat says how often and when last, and moves the entry up', () => {
    expect(eventWhen(BLOCKED)).toBe(1791394800);
    expect(eventWhen(POWER)).toBe(1791394000);
    expect(repeatedText(POWER)).toBe('');
    expect(repeatedText(BLOCKED)).toMatch(/^3 times, the last at \d/);
    expect(needsALook(BLOCKED)).toBe(true);
    expect(needsALook(POWER)).toBe(false);
  });

  it('says how long ago in the person’s language', async () => {
    const now = 1791400000;
    expect(agoText(now - 3, now)).toBe('Just now');
    expect(agoText(now - 45, now)).toBe('45 seconds ago');
    expect(agoText(now - 600, now)).toBe('10 minutes ago');
    expect(agoText(now - 7200, now)).toBe('2 hours ago');
    expect(agoText(now - 3 * 86400, now)).toBe('3 days ago');
    await setLanguage('de');
    expect(agoText(now - 600, now)).toBe('vor 10 Minuten'); // it read "10m ago" in every language
  });

  it('an entry leads to the page the server named, else to the Event Log', async () => {
    expect(eventPlace(BACKUP)).toMatchObject({ route: 'backup', name: 'Backup', label: 'Open Backup' });
    expect(eventPlace(POWER)).toMatchObject({ route: 'power', name: 'Power', label: 'Open Power' });
    expect(eventPlace(BLOCKED)).toMatchObject({ route: 'events', label: 'Open Event Log' });
    expect(eventPlace({ link: 'no-such-place' }).route).toBe('events');
    const open = vi.spyOn(ROUTES, 'backup').mockImplementation(() => {});
    eventPlace(BACKUP).open();
    expect(open).toHaveBeenCalled();
    open.mockRestore();
    await setLanguage('de');
    expect(eventPlace({ link: 'drives' }).label).toBe('Laufwerkszustand öffnen');
  });

  it('every place the server can name has a name here', async () => {
    const { readFileSync } = await import('node:fs');
    const store = readFileSync('backend/event_store.py', 'utf8');
    const places = new Set([...store.matchAll(/^    \("[a-z_.]+", "([a-z]+)"\),$/gm)].map((m) => m[1]));
    expect(places.size).toBeGreaterThan(8);
    for (const place of places) {
      expect(eventPlace({ link: place }).route, place).toBe(place);
    }
  });
});

describe('the bell', () => {
  beforeEach(() => {
    localStorage.clear();
    bell.resetCheckedEventsState();
    vi.clearAllMocks();
    document.body.innerHTML = '<span id="dock-notif-badge"></span><div id="notif-center-list"></div><div id="events-list"></div>';
    state.latestStats = { events: [BLOCKED, BACKUP, POWER] };
  });
  afterEach(async () => {
    await setLanguage('en');
    state.latestStats = null;
  });

  it('lists what asks for attention, in the reader’s language, and counts only that', async () => {
    expect(bell.bellEvents().map((e) => e.id)).toEqual([9, 8]); // "Power is back" is in the Event Log
    expect(bell.bellEvents(null)).toEqual([]);
    bell.updateNotificationBadge();
    expect(document.getElementById('dock-notif-badge').textContent).toBe('2');
    bell.renderNotificationCenter();
    const rows = () => [...document.querySelectorAll('.notif-center-item')];
    expect(rows().map((r) => r.querySelector('.notif-center-title').textContent)).toEqual(['Address blocked', 'Backup failed: Photos']);
    expect(rows()[0].querySelector('.notif-center-when').textContent).toContain('3 times, the last at');
    await setLanguage('de'); // the bell kept the server's English, and the old language until the next entry
    expect(rows()[1].querySelector('.notif-center-title').textContent).toBe('Sicherung fehlgeschlagen: Photos');
    expect(rows()[1].querySelector('.notif-center-msg').textContent).toContain('disk full');
  });

  it('an entry that is reported again is unread again', () => {
    bell.markEventChecked(BLOCKED);
    expect(bell.isEventChecked(BLOCKED)).toBe(true);
    expect(bell.isEventChecked({ ...BLOCKED, count: 4, last_ts: 1791395000 })).toBe(false);
  });

  it('"Mark all read" is saved with the account, and read marks follow the person', () => {
    expect(bell.markAllRead()).toBe(1791394800);
    expect(api.put).toHaveBeenCalledWith('/api/auth/me/preferences', { events_seen: 1791394800 });
    expect(bell.bellEvents().every(bell.isEventChecked)).toBe(true);
    expect(bell.markAllRead([])).toBe(0);
    // another person signs in on this browser: they do not inherit the marks
    ZettEventBus.emit('session:user', { username: 'ana', preferences: {} });
    expect(bell.isEventChecked(BACKUP)).toBe(false);
    // the same person on another device: what the account has seen is read here too
    ZettEventBus.emit('session:user', { username: 'ana', preferences: { events_seen: 1791394150 } });
    expect(bell.isEventChecked(BACKUP)).toBe(true);
    expect(bell.isEventChecked(BLOCKED)).toBe(false);
    bell.followReader(null);
    expect(bell.isEventChecked(BACKUP)).toBe(true);
  });

  it('the Event Log shows every entry with its count and follows the language', async () => {
    initEvents();
    const text = () => document.getElementById('events-list').textContent;
    expect(text()).toContain('Power is back');
    expect(text()).toContain('3 times, the last at');
    await setLanguage('de');
    expect(text()).toContain('Sicherung fehlgeschlagen: Photos'); // the open log kept the old language
    renderEventLog([{ ...BLOCKED, count: 4, last_ts: 1791395000 }, BACKUP, POWER]);
    expect(text()).toContain('4-mal, zuletzt um');
    expect(document.getElementById('btn-clear-events')).toBeNull();
  });
});
