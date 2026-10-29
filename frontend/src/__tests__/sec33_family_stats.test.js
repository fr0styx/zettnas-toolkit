import { describe, it, expect, beforeEach, vi } from 'vitest';
import { applyStats } from '../components/dashboard.js';
import { state } from '../state.js';

// SEC-33: a kid or guest gets only the desktop part of the stats; the desktop must still draw.
const FAMILY = {
  name: 'nas',
  status: '-- OK',
  storage: { used: '1TB', total: '4TB', pct: 25 },
  system: { uptime_str: '2d', uptime_sec: 172800, hostname: 'nas' },
  uptime: '2d',
  layout: { order: ['clock'] },
};

describe('the family view of the stats', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="screen">
        <span class="nas-name" id="nasName">NAS</span>
        <span class="pill" id="statusPill"><span id="statusText"></span></span>
        <span id="clock"></span>
        <section id="diskRow"></section>
      </div>`;
    state.latestStats = null;
  });

  it('draws without errors when cpu, memory, disks and the rest are missing', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {});
    applyStats(FAMILY);
    applyStats({ uptime: '3d' });
    expect(err).not.toHaveBeenCalled();
    expect(document.getElementById('statusPill').className).toBe('pill');
    err.mockRestore();
  });
});
