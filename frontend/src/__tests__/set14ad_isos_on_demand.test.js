import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api } from '../api.js';
import { vmState } from '../components/vm/state.js';
import { loadIsos, fillIsoSelect } from '../components/vm/isos.js';
import { loadVmDashboard } from '../components/vm-manager.js';

beforeEach(() => {
  vi.restoreAllMocks();
  vmState.isos = [];
});

describe('installer folders are read on demand (SET-14, VMs 28)', () => {
  it('a window refresh does not read them', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue([]);
    await loadVmDashboard();
    expect(get.mock.calls.map(([u]) => u)).not.toContain('/api/vms/isos');
  });

  it('a dialog reads them and fills its list, keeping the choice', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([{ name: 'debian.iso', path: '/x/debian.iso', size_formatted: '0.6 GB' }]);
    await loadIsos();
    document.body.innerHTML = '<select id="s"><option value="">None</option></select>';
    const s = document.getElementById('s');
    fillIsoSelect(s, '/x/debian.iso');
    expect([...s.options].map((o) => o.value)).toEqual(['', '/x/debian.iso']);
    expect(s.value).toBe('/x/debian.iso');
  });

  it('a failed read keeps the last list', async () => {
    vmState.isos = [{ name: 'a.iso', path: '/a.iso' }];
    vi.spyOn(api, 'get').mockRejectedValue(new Error('down'));
    expect(await loadIsos()).toEqual([{ name: 'a.iso', path: '/a.iso' }]);
  });
});
