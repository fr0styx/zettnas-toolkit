import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { eventLook } from '../event-level.js';

const src = (p) => readFileSync(resolve(__dirname, '..', p), 'utf8');

describe('the most serious events are drawn as errors (SET-03)', () => {
  it('knows the five levels the server sends', () => {
    expect(eventLook('critical')).toBe('error');
    expect(eventLook('CRITICAL')).toBe('error');
    expect(eventLook('error')).toBe('error');
    expect(eventLook('warning')).toBe('warning');
    expect(eventLook('success')).toBe('success');
    expect(eventLook('info')).toBe('info');
    expect(eventLook(undefined)).toBe('info');
    expect(eventLook('something-new')).toBe('info');
  });

  it('is the one list the log, the bell, its preview and the event dialog use', () => {
    for (const file of ['components/events.js', 'components/dock/notifications.js', 'components/dock/dock-manager.js', 'modals.js']) {
      const code = src(file);
      expect(code, file).toMatch(/eventLook\(|eventView\(/); // eventView() draws from eventLook() (SET-13)
      expect(code, file).not.toMatch(/\.level === 'error'/);
    }
  });
});
