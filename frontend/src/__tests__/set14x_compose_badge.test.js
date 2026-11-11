import { describe, it, expect, beforeEach } from 'vitest';
import { setComposeBadge } from '../components/container-modal.js';

beforeEach(() => {
  document.body.innerHTML = '<span id="ci-compose-source-badge"></span>';
});
const badge = () => document.getElementById('ci-compose-source-badge').textContent;

describe('the Compose tab says what is shown (SET-14, Apps 26)', () => {
  const disk = { source: 'disk', compose_yaml: 'services: {from: disk}', masked_yaml: 'services: {rebuilt: masked}', compose_file_path: '/mnt/user/stacks/a/compose.yml' };

  it('masked, a disk file is not claimed', () => {
    setComposeBadge(disk, disk.masked_yaml);
    expect(badge()).not.toContain('Read from Disk');
    expect(badge()).toContain('Rebuilt from the running app');
  });

  it('unmasked, the disk file is named as such', () => {
    setComposeBadge(disk, disk.compose_yaml);
    expect(badge()).toContain('Read from Disk');
  });

  it('a person without the right gets the masked file as compose_yaml too: still rebuilt', () => {
    const same = { ...disk, compose_yaml: disk.masked_yaml };
    setComposeBadge(same, same.compose_yaml);
    expect(badge()).not.toContain('Read from Disk');
  });
});
