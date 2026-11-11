// SET-14: restoring an app backup says what became of the app.
import { describe, it, expect } from 'vitest';
import { restoredSaid } from '../components/management/app-restore-said.js';

describe('what a restored app backup says', () => {
  it('names the folders and what became of the app', () => {
    const two = ['/mnt/user/appdata/plex', '/mnt/user/media'];
    expect(restoredSaid({ restored_mounts: two, outcome: 'running_again' }, 'plex')).toEqual(['"plex" was restored (2 folders) and runs again.', 'success']);
    expect(restoredSaid({ restored_mounts: ['/a'], outcome: 'stopped_kept' }, 'plex')[0]).toBe('"plex" was restored (1 folder). It was stopped before and stays stopped.');
    expect(restoredSaid({ restored_mounts: two, outcome: 'start_failed' }, 'plex')[1]).toBe('warn');
    // "successfully restored (0 paths restored)!" every time, and "recreated" when nothing had started
    expect(restoredSaid({ restored_mounts: two, outcome: 'files_only', compose_path: '/data/stacks/plex/docker-compose.yml' }, 'plex')).toEqual([
      'The folders of "plex" were restored (2), but the app itself is not installed any more. Install it again from the catalog; its Compose file is kept at /data/stacks/plex/docker-compose.yml.',
      'warn',
    ]);
    expect(restoredSaid({ restored_mounts: [] }, 'plex')[0]).toBe('The folders of "plex" were restored (0), but the app itself is not installed any more. Install it again from the catalog.');
    expect(restoredSaid(null, 'plex')[1]).toBe('warn');
  });
});

describe('the small things in Apps', () => {
  it('a stack\'s Web UI link names this server, not "[HOST]"', async () => {
    const { readFileSync } = await import('node:fs');
    const code = readFileSync('frontend/src/components/stack-modal.js', 'utf8');
    expect(code).toContain("c.webui_url.replace('[HOST]', window.location.hostname)");
    for (const f of ['frontend/src/components/container-modal.js', 'frontend/src/components/containers-manager.js']) {
      expect(readFileSync(f, 'utf8'), f).toContain('res?.backup?.filename');
    }
  });
});
