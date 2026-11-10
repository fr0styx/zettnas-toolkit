import { describe, it, expect } from 'vitest';
import { routeConflictText } from '../components/management/network.js';

describe('Tailscale routes over the NAS network', () => {
  it('say why Accept Routes is off', () => {
    expect(routeConflictText({ route_conflicts: [{ peer: 'router', route: '192.168.50.0/24' }] })).toContain('router offers 192.168.50.0/24');
    expect(routeConflictText({ route_conflicts: [] })).toBe('');
    expect(routeConflictText({})).toBe('');
    expect(routeConflictText(null)).toBe('');
  });
});
