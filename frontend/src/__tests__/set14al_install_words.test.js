import { describe, it, expect, afterEach } from 'vitest';
import { setLanguage } from '../i18n.js';
import { serverSaid } from '../server-text.js';

afterEach(async () => {
  await setLanguage('en');
});

describe('install progress in the reader\'s language (SET-14, Apps)', () => {
  it('a line with a key is translated; one without stays as sent', async () => {
    await setLanguage('de');
    const ev = { step: 'pull', message: 'Pulling x from registry (downloading layers)...', text: { msg_key: 'install.pulling', params: { image: 'jellyfin:10' } } };
    expect(serverSaid(ev, ev.message)).toBe('jellyfin:10 wird heruntergeladen…');
    expect(serverSaid({ message: 'layer 3/7' }, 'layer 3/7')).toBe('layer 3/7');
  });
});
