import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  initContainersManager,
  openContainersManager,
  renderContainersWindowTable,
  _resetCwAutoRefreshForTesting,
  stopCwAutoRefresh,
  CW_VIRTUALIZE_MIN_ROWS,
} from '../components/containers-manager.js';
import { clearSelectedContainers, getSelectedContainerIds, toggleContainerSelected } from '../components/docker-table.js';
import { api } from '../api.js';
import { DockManager } from '../components/dock.js';

const make = (n, extra = () => ({})) =>
  Array.from({ length: n }, (_, i) => ({
    id: `c${i}`,
    name: `app-${String(i).padStart(3, '0')}`,
    image: 'nginx:latest',
    state: i % 2 ? 'exited' : 'running',
    status: 'Up 1 hour',
    ports: [],
    cpu_pct: 0,
    mem_used: 0,
    ...extra(i),
  }));

const tbody = () => document.getElementById('cw-docker-containers-tbody');
const dataRows = () => [...tbody().querySelectorAll('tr:not(.cw-virtual-spacer)')];
const spacer = (which) => tbody().querySelector(`tr.cw-virtual-spacer[data-key="__cw-spacer-${which}"]`);
const nextFrame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));

describe('Containers table virtualization', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = '<div id="os-dock-container"><div id="os-dock"></div></div>';
    window._containersManagerInitialized = false;
    window.DockManager = DockManager;
    DockManager.windows = {};
    vi.spyOn(api, 'get').mockResolvedValue([]);
    _resetCwAutoRefreshForTesting();
    clearSelectedContainers();
    initContainersManager();
    openContainersManager();
    // Filter/search state is module-level; start every test from "All".
    document.querySelector('.cw-filter-btn[data-filter="all"]').click();
  });

  afterEach(() => {
    stopCwAutoRefresh();
    vi.restoreAllMocks();
  });

  it('renders every row below the threshold, with no spacers', () => {
    renderContainersWindowTable(make(CW_VIRTUALIZE_MIN_ROWS - 1));
    expect(dataRows().length).toBe(CW_VIRTUALIZE_MIN_ROWS - 1);
    expect(tbody().querySelector('.cw-virtual-spacer')).toBeNull();
  });

  it('renders only a window of rows for large inventories', () => {
    renderContainersWindowTable(make(300));
    const rows = dataRows();
    expect(rows.length).toBeGreaterThan(10);
    expect(rows.length).toBeLessThan(60);
    expect(spacer('top').style.display).toBe('none');
    expect(parseInt(spacer('bottom').firstElementChild.style.height, 10)).toBeGreaterThan(0);
  });

  it('moves the window on scroll and keeps selection for off-screen rows', async () => {
    renderContainersWindowTable(make(300));
    toggleContainerSelected('c0', true);
    const firstRow = dataRows()[0];
    expect(firstRow.dataset.key).toBe('c0');

    // Pretend the list is scrolled ~150 rows down.
    vi.spyOn(tbody(), 'getBoundingClientRect').mockReturnValue({ top: -150 * 52, bottom: 0, left: 0, right: 0, height: 0, width: 0 });
    // The scroll listener sits on the nearest scrolling ancestor (or window).
    for (let el = tbody(); el; el = el.parentElement) el.dispatchEvent(new Event('scroll'));
    window.dispatchEvent(new Event('scroll'));
    await nextFrame();

    const keys = dataRows().map((r) => r.dataset.key);
    expect(keys).toContain('c150');
    expect(keys).not.toContain('c0');
    expect(spacer('top').style.display).toBe('');
    expect(getSelectedContainerIds()).toEqual(['c0']);
  });

  it('a live re-render while scrolled keeps the window (spacer rows are not wiped)', async () => {
    const list = make(300);
    renderContainersWindowTable(list);
    vi.spyOn(tbody(), 'getBoundingClientRect').mockReturnValue({ top: -150 * 52, bottom: 0, left: 0, right: 0, height: 0, width: 0 });
    for (let el = tbody(); el; el = el.parentElement) el.dispatchEvent(new Event('scroll'));
    window.dispatchEvent(new Event('scroll'));
    await nextFrame();
    expect(tbody().firstElementChild.classList.contains('cw-virtual-spacer')).toBe(true);

    renderContainersWindowTable(list.map((c) => ({ ...c, cpu_pct: 5 })));

    const keys = dataRows().map((r) => r.dataset.key);
    expect(keys).toContain('c150');
    expect(spacer('top').style.display).toBe('');
  });

  it('select-all only selects containers matching the current filter', () => {
    renderContainersWindowTable(make(10));
    document.querySelector('.cw-filter-btn[data-filter="stopped"]').click();
    const selectAll = document.getElementById('cw-docker-select-all');
    selectAll.checked = true;
    selectAll.dispatchEvent(new Event('change'));
    const selected = getSelectedContainerIds().sort();
    expect(selected).toEqual(['c1', 'c3', 'c5', 'c7', 'c9']);
  });

  it('switches back to full rendering when the list shrinks', () => {
    renderContainersWindowTable(make(300));
    renderContainersWindowTable(make(5));
    expect(dataRows().length).toBe(5);
    expect(tbody().querySelector('.cw-virtual-spacer')).toBeNull();
  });
});
