import { describe, it, expect } from 'vitest';
import { eventText } from '../event-text.js';

describe('activity-log entries in the reader\'s language (NUX-3)', () => {
  it('builds the text from its keys, translating values that are references', () => {
    const e = {
      title: 'Drive sdb: Replace soon',
      message: 'x',
      details: {
        title_key: 'alert.drive_verdict.title',
        msg_key: 'alert.drive_verdict.msg',
        params: { dev: 'sdb', label: { key: 'dh.label.soon_replace', default: 'Replace soon' }, summary: { key: 'nope.title', default: 'Parts could not be read' } },
      },
    };
    expect(eventText(e)).toEqual({ title: 'Drive sdb: Replace soon', message: 'Parts could not be read. Open Drive Health for what to do.' });
  });

  it('leaves older entries as they were', () => {
    expect(eventText({ title: 'Recycle Bin emptied', message: '3 items' })).toEqual({ title: 'Recycle Bin emptied', message: '3 items' });
    expect(eventText(null)).toEqual({ title: '', message: '' });
  });
});
