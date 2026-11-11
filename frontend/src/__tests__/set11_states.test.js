// SET-11: one block for loading, could not load, nothing there and "look but not change"; and one
// way to show a text the server sends in the reader's language.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { markReadOnly, showState, stateBlock } from '../components/state-block.js';
import { resolveParams, serverSaid, weekdayNames } from '../server-text.js';
import { explain } from '../error-text.js';
import { eventText } from '../event-text.js';
import * as i18n from '../i18n.js';

describe('the state block', () => {
  it('says each state in words, with the right kind of announcement', () => {
    const loading = stateBlock('loading');
    expect(loading.textContent).toBe('Loading…');
    expect(loading.getAttribute('role')).toBe('status');
    expect(loading.getAttribute('aria-busy')).toBe('true');
    const failed = stateBlock('failed');
    expect(failed.textContent).toBe('This could not be loaded.');
    expect(failed.getAttribute('role')).toBe('alert');
    expect(stateBlock('empty').textContent).toBe('Nothing here yet.');
    const look = stateBlock('readonly');
    expect(look.textContent).toBe('You can look at this, but only an administrator can change it.');
    expect(look.getAttribute('role')).toBe('note');
    expect(stateBlock('something-else').classList.contains('is-failed')).toBe(true);
  });

  it('a failure offers "Try again", an empty place its next step', () => {
    const retry = vi.fn();
    const failed = stateBlock('failed', { text: 'The pools could not be read.', detail: 'offline', retry });
    expect(failed.querySelector('.state-block-text').textContent).toBe('The pools could not be read.');
    expect(failed.querySelector('.state-block-detail').textContent).toBe('offline');
    failed.querySelector('[data-try-again]').click();
    expect(retry).toHaveBeenCalledTimes(1);
    expect(stateBlock('failed').querySelector('button')).toBeNull();
    const run = vi.fn();
    const empty = stateBlock('empty', { text: 'No backups yet.', action: { label: 'Add a backup', run } });
    empty.querySelector('[data-state-action]').click();
    expect(run).toHaveBeenCalledTimes(1);
    expect(empty.querySelector('button').textContent).toBe('Add a backup');
  });

  it('replaces what a container shows, and marks a part as look-only once', () => {
    const box = document.createElement('div');
    box.innerHTML = '<p>old</p>';
    showState(box, 'loading');
    expect(box.children).toHaveLength(1);
    expect(box.textContent).toBe('Loading…');
    expect(showState(null, 'loading')).toBeNull();
    box.innerHTML = '<form></form>';
    markReadOnly(box);
    markReadOnly(box, 'again');
    expect(box.querySelectorAll('.state-block.is-readonly')).toHaveLength(1);
    expect(box.firstElementChild.classList.contains('is-readonly')).toBe(true);
    expect(box.querySelector('form')).not.toBeNull();
  });

  it('never reads a text as markup', () => {
    const block = stateBlock('failed', { text: '<img src=x onerror=alert(1)>' });
    expect(block.querySelector('img')).toBeNull();
  });
});

describe('a text the server sends', () => {
  afterEach(async () => {
    await i18n.setLanguage('en');
  });

  it('is translated from its key and values when the server said how', async () => {
    const body = { detail: 'This account can be signed in Mon-Fri 07:00-20:00 (server time).', text: { msg_key: 'srv.outside_hours_days', params: { start: '07:00', end: '20:00', days: { weekdays: [0, 1, 2, 3, 4] } } } };
    expect(serverSaid(body)).toBe("You can sign in on Mon, Tue, Wed, Thu, Fri from 07:00 to 20:00 (the server's time).");
    expect(explain(body.detail, 'outside_signin_hours', body)).toBe(serverSaid(body));
    await i18n.setLanguage('de');
    expect(serverSaid(body)).toContain('07:00 bis 20:00');
    expect(serverSaid(body)).toContain('Mo');
    expect(serverSaid(body)).not.toContain('This account');
  });

  it('is shown as it came when the server did not say how', () => {
    expect(serverSaid({ detail: 'Plain sentence.' })).toBe('Plain sentence.');
    expect(serverSaid({ message: 'Done.' })).toBe('Done.');
    expect(serverSaid(null, 'fallback')).toBe('fallback');
    expect(serverSaid({ text: 'a plain string' }, 'own')).toBe('own');
    expect(explain('Plain sentence.', 'conflict', { detail: 'Plain sentence.' })).toContain('Plain sentence.');
  });

  it('reads values that are texts or weekdays, and events the same way', () => {
    expect(weekdayNames([5, 6], 'en')).toBe('Sat, Sun');
    expect(weekdayNames([], 'en')).toBe('');
    expect(resolveParams({ n: 3, when: { weekdays: [0] }, what: { key: 'common.cancel', default: 'Cancel' } })).toEqual({ n: 3, when: 'Mon', what: 'Cancel' });
    const event = { title: 'T', message: 'M', details: { msg_key: 'srv.outside_hours_daily', params: { start: '08:00', end: '09:00' } } };
    expect(eventText(event).message).toBe("You can sign in every day from 08:00 to 09:00 (the server's time).");
    expect(serverSaid(event)).toBe(eventText(event).message);
  });
});
