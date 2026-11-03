/** NUX-20: the container table's button tooltips read as translatable words. */
import { describe, it, expect } from 'vitest';
import { buildContainerRowInner } from '../components/docker-table.js';

const titles = (html) => {
  const tr = document.createElement('tr');
  tr.innerHTML = html;
  return [...tr.querySelectorAll('[title]')].map((el) => el.getAttribute('title'));
};

describe('container row tooltips (NUX-20)', () => {
  it('names each action for a running container in a stack', () => {
    const got = titles(buildContainerRowInner({ id: 'c1', name: 'web', state: 'running', stack: 'site', primary_port: 8080, webui_url: 'http://[HOST]:8080', ports: [] }, 'nas.local', { has_update: true }));
    for (const w of ['Open & Edit Stack: site', 'Open Web UI (Port 8080)', 'Click to update web to latest image', 'Inspect web', 'Edit web', 'Update web to latest image', 'Destroy / Delete web', 'Restart web', 'Stop web', 'Select web']) {
      expect(got).toContain(w);
    }
  });

  it('offers Start for a stopped container', () => {
    const got = titles(buildContainerRowInner({ id: 'c2', name: 'db', state: 'exited', ports: [] }, 'nas.local'));
    expect(got).toContain('Start db');
    expect(got).not.toContain('Stop db');
  });
});
