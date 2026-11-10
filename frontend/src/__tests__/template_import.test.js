/** RES-8: an app imported from another system's template says it is untested. */
import { describe, it, expect } from 'vitest';
import { renderSideloadInspection } from '../components/management/docker.js';

describe('imported templates', () => {
  it('say where they come from and that Kiboto has not tested them', () => {
    const box = document.createElement('div');
    renderSideloadInspection({ name: 'jellyfin', image: 'lscr.io/linuxserver/jellyfin', untested: true, origin: 'Unraid template' }, 'review_required', ['Uses the host device /dev/dri'], box);
    expect(box.textContent).toContain('Imported from: Unraid template');
    expect(box.textContent).toContain('/dev/dri');
  });

  it('say nothing of it for a manifest of your own', () => {
    const box = document.createElement('div');
    renderSideloadInspection({ name: 'mine', image: 'me/app' }, 'verified', [], box);
    expect(box.textContent).not.toContain('Imported from');
    renderSideloadInspection({ name: 'x' }, 'verified', [], null);
  });
});
