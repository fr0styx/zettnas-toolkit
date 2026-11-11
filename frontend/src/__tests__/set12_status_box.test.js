// SET-12: one status box with five states, an icon and a word in each row.
import { describe, it, expect } from 'vitest';
import { canProtect, protectionRow, statusBoxHtml, statusSaid, statusState } from '../components/management/status-box.js';

const rowText = (i) => `${i.kind} ${i.subject || ''}`.trim();
const owner = { scopes: ['*'] };
const family = { scopes: ['files:read'] };

describe('the state of the box', () => {
  it('is "checking" before an answer and "unknown" after a failure, never "fine"', () => {
    expect(statusState({}).level).toBe('checking');
    const failed = statusState({ error: new Error('offline') });
    expect(failed.level).toBe('unknown');
    expect(failed.reason).toBe('offline');
    expect(statusBoxHtml(statusState({}))).toContain('Checking how things are');
    const html = statusBoxHtml(failed);
    expect(html).toContain('Kiboto could not check how things are');
    expect(html).toContain('data-ov-retry');
    expect(html).not.toContain('Everything is fine');
    expect(statusBoxHtml(undefined)).toContain('Checking');
  });

  it('is fine only when every check ran and found nothing', () => {
    expect(statusState({ summary: { ok: true, items: [] } }).level).toBe('fine');
    const missed = statusState({ summary: { ok: false, items: [], unchecked: ['drives', 'power'] } });
    expect(missed.level).toBe('look');
    const html = statusBoxHtml(missed);
    expect(html).toContain('2 checks did not run');
    expect(html).not.toContain('Everything is fine');
  });

  it('says "Problem" for a critical row and "Needs a look" for a warning, in words', () => {
    const state = statusState({
      summary: { items: [{ level: 'critical', kind: 'drive_failing', subject: 'sdb', open: 'drives' }, { level: 'warning', kind: 'backup_overdue', subject: 'Photos', open: 'nowhere' }] },
      rowText,
      canOpen: (place) => place === 'drives',
    });
    expect(state.level).toBe('problem');
    const html = statusBoxHtml(state);
    expect(html).toContain('ov-problem');
    expect(html.match(/ov-word/g)).toHaveLength(2);
    expect(html).toContain('Problem');
    expect(html).toContain('Needs a look');
    expect(html).toContain('data-ov-open="drives"');
    expect(html).not.toContain('data-ov-open="nowhere"'); // a button only where it leads somewhere
    expect(statusSaid(state)).toBe('Problem: 2 things need attention');
    const look = statusState({ summary: { items: [{ level: 'warning', kind: 'x' }] }, rowText });
    expect(look.level).toBe('look');
    expect(statusBoxHtml(look)).toContain('ov-attention');
    expect(statusSaid(look)).toBe('1 thing needs attention');
  });

  it('counts a missing copy outside the NAS as a thing to look at, in the same list', () => {
    const state = statusState({ summary: { ok: true, items: [] }, protection: { level: 'none', copies: 0 }, user: owner });
    expect(state.level).toBe('look');
    expect(state.rows).toHaveLength(1);
    expect(statusBoxHtml(state)).toContain('data-ov-protect');
    const good = statusState({ summary: { ok: true, items: [] }, protection: { level: 'good', copies: 1, last_good: 1793091600 } });
    expect(good.level).toBe('fine');
    expect(statusBoxHtml(good)).toContain('1 current copy outside this NAS');
    expect(statusSaid(good)).toBe('All is well.');
  });

  it('offers "Protect this NAS" only to someone who can set a backup up', () => {
    expect(canProtect(owner)).toBe(true);
    expect(canProtect({ scopes: ['backup:manage'] })).toBe(true);
    expect(canProtect(family)).toBe(false);
    expect(canProtect(null)).toBe(true); // not known yet: the server decides
    expect(protectionRow({ level: 'none' }, family)).toMatchObject({ protect: false, tellAdmin: true });
    expect(protectionRow({ level: 'stale', last_good: null }, owner).text).toContain('from ?');
    expect(protectionRow({ level: 'good' }, owner)).toBeNull();
    expect(protectionRow(null, owner)).toBeNull();
  });

  it('never reads a text as markup', () => {
    const state = statusState({ summary: { items: [{ level: 'warning', kind: '<img src=x>' }] }, rowText });
    expect(statusBoxHtml(state)).not.toContain('<img');
    expect(statusBoxHtml(statusState({ error: new Error('<b>x</b>') }))).not.toContain('<b>x</b>');
  });
});
