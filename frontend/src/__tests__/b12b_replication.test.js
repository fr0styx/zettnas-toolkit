import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
const { api } = await import('../api.js');

const setup = () => {
  document.body.innerHTML = `<button class='mgmt-inner-tab' data-tab-target='mgmt-pane-storage-replication'></button>
    <table><tbody id='replication-jobs-tbody'></tbody></table><table><tbody id='replication-history-tbody'></tbody></table>`;
  return document.querySelector('.mgmt-inner-tab');
};

describe('B12b (REL-5): replication shows where it can run', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  it('shows the tab where this NAS can replicate', async () => {
    const tab = setup();
    api.get.mockResolvedValue({ jobs: [], available: true, reason: '' });
    const { revealReplicationTab } = await import('../components/management/network.js');
    await revealReplicationTab();
    expect(tab.style.display).toBe('');
  });

  it('keeps it hidden elsewhere, and asks again after a failed check', async () => {
    const tab = setup();
    api.get.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ jobs: [], available: false, reason: 'TrueNAS replicates its own pools' });
    const { revealReplicationTab } = await import('../components/management/network.js');
    await revealReplicationTab();
    await revealReplicationTab();
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(tab.style.display).toBe('none');
  });

  it('the list says why it cannot run, and shows each job as it is', async () => {
    setup();
    const { fetchAndRenderReplication } = await import('../components/management/network.js');
    api.get.mockImplementation(async (url) => (url.endsWith('/jobs') ? { jobs: [], available: false, reason: 'TrueNAS replicates its own pools' } : { history: [] }));
    await fetchAndRenderReplication();
    expect(document.getElementById('replication-jobs-tbody').textContent).toContain('TrueNAS replicates its own pools');
    const job = { id: 'j1', name: 'DR', source_pool: 'tank', source_dataset: 'family', target_type: 'local', target_pool: 'backup', schedule: 'daily', bandwidth_limit_kbps: 10240, retention_count: 7, last_status: 'error', last_error: 'out of space' };
    api.get.mockImplementation(async (url) => (url.endsWith('/jobs') ? { jobs: [job], available: true } : { history: [] }));
    await fetchAndRenderReplication();
    const row = document.getElementById('replication-jobs-tbody').textContent;
    expect(row).toContain('tank/family');
    expect(row).toContain('10 MB/s');
    expect(row).toContain('error');
  });
});
