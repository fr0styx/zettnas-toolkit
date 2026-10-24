import { describe, it, expect, vi } from 'vitest';
import { routeFromHash, openRoute } from '../router.js';

describe('deep links (UX-4)', () => {
  it('reads #/place and #/place/sub', () => {
    expect(routeFromHash('#/apps')).toBe('apps');
    expect(routeFromHash('#/apps/catalog')).toBe('apps/catalog');
    expect(routeFromHash('#/shares/')).toBe('shares');
    expect(routeFromHash('#/nope')).toBe(null);
    expect(routeFromHash('#top')).toBe(null);
  });

  it('opens the one place for each job', () => {
    window.openContainersManager = vi.fn();
    window.openManagementSection = vi.fn();
    expect(openRoute('#/apps/catalog')).toBe(true);
    expect(window.openContainersManager).toHaveBeenCalledWith({ view: 'catalog' });
    openRoute('#/backup');
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-backups');
    expect(openRoute('#/unknown')).toBe(false);
  });
});
