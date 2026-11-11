// The history chart (SET-13): it says when it has nothing, shows what was measured and nothing
// else, and its row of values says that it is a stored sample.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const drawn = [];
vi.mock('chart.js', () => {
  class Chart {
    static register() {}
    static getChart() {
      return null;
    }
    constructor(_ctx, config) {
      drawn.push(config);
    }
    destroy() {}
    resetZoom() {}
  }
  Chart.defaults = { font: {} };
  const part = {};
  return { Chart, LineController: part, LineElement: part, PointElement: part, LinearScale: part, CategoryScale: part, Legend: part, Tooltip: part, Filler: part };
});
vi.mock('../api.js', () => ({ api: { get: vi.fn() } }));

const { api } = await import('../api.js');
const { state } = await import('../state.js');
const { setLanguage } = await import('../i18n.js');
const { initMetricsChart, fetchAndRenderMetrics, stopMetricsRefresh, showMetricsPage } = await import('../components/metrics-chart.js');
const view = await import('../components/metrics-view.js');

const SAMPLE = {
  ts: 1700000000, cpu_temp: 45, cpu_util: 12, mem_pct: 38,
  net_rx: 1548576, net_tx: 524288, disk_read: 2097152, disk_write: 1048576,
  disks: [{ name: 'sda', temp: 34, standby: false }, { name: 'sdb', temp: null, standby: true }, { name: 'sdc', temp: 58, standby: false }],
  fans: [950, 1100, 4200, null],
};
const LATER = { ...SAMPLE, ts: 1700000300, disks: [{ name: 'sda', temp: 35, standby: false }, { name: 'sdb', temp: 31, standby: false }], fans: [900, 1150, 4100, 600] };
const strip = () => document.getElementById('metrics-device-summary-strip').textContent;
const said = () => document.querySelector('.metrics-chart-state');

describe('the history chart', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stopMetricsRefresh();
    drawn.length = 0;
    state.latestStats = null;
    HTMLCanvasElement.prototype.getContext = () => ({});
    document.body.innerHTML = `
      <select id="metrics-range-select"><option value="1h">1h</option><option value="24h" selected>24h</option><option value="7d">7d</option></select>
      <button id="metrics-reset-zoom-btn" style="display:none;">Reset Zoom</button>
      <div class="metrics-device-filter-row">
        <button class="metrics-device-btn active" data-metric-group="all">All</button>
        <button class="metrics-device-btn" data-metric-group="disks">Storage Disks</button>
        <button class="metrics-device-btn" data-metric-group="network">Network Bandwidth</button>
        <button class="metrics-device-btn" data-metric-group="fans">Cooling Fans</button>
      </div>
      <div id="metrics-device-summary-strip"></div>
      <div><canvas id="metricsChart"></canvas></div>`;
    initMetricsChart();
  });
  afterEach(async () => {
    vi.useRealTimers();
    document.querySelector('[data-metric-group="all"]').click();
    await setLanguage('en');
  });

  it('the row of values says it is a stored sample, and a sleeping drive says "Asleep"', async () => {
    state.latestStats = { net: { interfaces: { eth1: { rx: '250.0 MB/s', tx: '120.0 MB/s', is_physical: true } } } };
    api.get.mockResolvedValue([SAMPLE]);
    await fetchAndRenderMetrics(false);
    expect(strip()).toMatch(/^Stored reading from \d/); // it looked like a live reading
    expect(strip()).toContain('Processor:45 °C · 12 %');
    expect(strip()).toContain('Memory:38 %');
    expect(strip()).toContain('sda:34 °C');
    expect(strip()).toContain('sdb:Asleep'); // it showed the temperature the drive had when it fell asleep
    expect(document.querySelector('.dmp-val.is-hot').textContent).toBe('58 °C');
    expect(strip()).toContain('Fan 1:950 RPM'); // "Rear Fan", "Drive Bay Fan", "CPU Fan" were one machine's
    expect(strip()).toContain('Fan 4:No reading');
    expect(strip()).toContain('Network:↓ 1.5 MB/s · ↑ 512.0 KB/s');
    expect(strip()).toContain('Drive activity:R 2.0 MB/s · W 1.0 MB/s');
    expect(strip()).not.toContain('eth1'); // live values were mixed into the stored row
    await setLanguage('de');
    expect(strip()).toContain('sdb:Schläft');
    expect(strip()).toContain('Lüfter 1:950 RPM');
  });

  it('says that it is loading, that there is nothing yet, and that it could not load', async () => {
    api.get.mockRejectedValueOnce(new Error('offline'));
    await fetchAndRenderMetrics(false);
    expect(said().querySelector('[role="alert"]').textContent).toContain('The history could not be loaded.'); // it went to the console only
    expect(said().querySelector('.state-block-detail').textContent).toBe('offline'); // what the server said, without "Error:"
    expect(strip()).toBe('');

    let answer;
    api.get.mockReturnValueOnce(new Promise((resolve) => { answer = resolve; }));
    const second = fetchAndRenderMetrics(false);
    expect(said().textContent).toBe('Loading…');
    expect(document.getElementById('metricsChart').hidden).toBe(true);
    answer([]);
    await second;
    expect(said().textContent).toContain('No history yet');
    expect(drawn).toHaveLength(0);

    api.get.mockRejectedValueOnce(new Error('offline again'));
    await fetchAndRenderMetrics(false);
    api.get.mockResolvedValueOnce([SAMPLE, LATER]);
    said().querySelector('[data-try-again]').click();
    await vi.waitFor(() => expect(drawn).toHaveLength(1));
    expect(said().hidden).toBe(true);
    expect(document.getElementById('metricsChart').hidden).toBe(false);
  });

  it('draws a gap where a drive slept and an axis that holds every value', async () => {
    api.get.mockResolvedValue([SAMPLE, LATER]);
    await fetchAndRenderMetrics(false);
    document.querySelector('[data-metric-group="disks"]').click();
    await vi.waitFor(() => expect(drawn.at(-1).data.datasets.map((d) => d.label)).toEqual(['sda (°C)', 'sdb (°C)', 'sdc (°C)']));
    const disks = drawn.at(-1);
    expect(disks.data.datasets[1].data).toEqual([null, 31]);
    expect(disks.data.datasets[2].data).toEqual([58, null]); // not in the later sample: a gap, not a line to it
    expect(disks.data.datasets.every((d) => d.spanGaps === false)).toBe(true);
    expect(disks.options.scales.y).toMatchObject({ min: 20, max: 65 });

    document.querySelector('[data-metric-group="fans"]').click();
    await vi.waitFor(() => expect(drawn.at(-1).data.datasets[0].label).toBe('Fan 1 (RPM)'));
    const fans = drawn.at(-1);
    expect(fans.data.datasets).toHaveLength(4);
    expect(fans.data.datasets[3].data).toEqual([null, 600]);
    expect(fans.options.scales.y.max).toBeGreaterThanOrEqual(4200); // the axis ended at 3,500 RPM
    expect(api.get).toHaveBeenCalledTimes(1); // the groups share the data that was read
  });

  it('is read again while it is on screen, and not once the page is closed', async () => {
    vi.useFakeTimers();
    api.get.mockResolvedValue([SAMPLE]);
    const canvas = document.getElementById('metricsChart');
    Object.defineProperty(canvas, 'offsetParent', { configurable: true, get: () => document.body });
    await fetchAndRenderMetrics(false);
    expect(api.get).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(view.REFRESH_MS + 50);
    expect(api.get).toHaveBeenCalledTimes(2); // it was read once, when the page opened
    Object.defineProperty(canvas, 'offsetParent', { configurable: true, get: () => null });
    await vi.advanceTimersByTimeAsync(view.REFRESH_MS * 3);
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it('opening the page wires it once and draws the chart', async () => {
    // the module is loaded when the page opens, not with Settings in the first seconds
    api.get.mockResolvedValue([SAMPLE]);
    await showMetricsPage();
    await showMetricsPage();
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(drawn.length).toBeGreaterThan(0);
  });

  it('switches the group buttons', () => {
    const all = document.querySelector('[data-metric-group="all"]');
    const net = document.querySelector('[data-metric-group="network"]');
    net.click();
    expect(all.classList.contains('active')).toBe(false);
    expect(net.classList.contains('active')).toBe(true);
    expect(all.getAttribute('aria-pressed')).toBe('false');
    expect(net.getAttribute('aria-pressed')).toBe('true');
  });
});

describe('what the chart makes of its data', () => {
  it('names drives and fans from the data', () => {
    expect(view.driveNames([SAMPLE, LATER])).toEqual(['sda', 'sdb', 'sdc']);
    expect(view.driveNames(null)).toEqual([]);
    expect(view.driveSeries([SAMPLE, LATER], 'sdb')).toEqual([null, 31]);
    expect(view.driveSeries([{ disks: [{ name: 'sdx', temp: 40, standby: true }] }, {}], 'sdx')).toEqual([null, null]);
    expect(view.fanSeries([SAMPLE]).map((f) => f.label)).toEqual(['Fan 1', 'Fan 2', 'Fan 3', 'Fan 4']);
    expect(view.fanSeries([{}])).toEqual([]);
  });

  it('fits the axis to the values', () => {
    expect(view.axisRange([[34, 35], [null, 58]], { floor: 20, step: 5 })).toEqual({ min: 20, max: 65 });
    expect(view.axisRange([[8, 12]], { floor: 20, step: 5 })).toEqual({ min: 5, max: 15 }); // a cold room is on the chart too
    expect(view.axisRange([[900, 4200]], { floor: 0, step: 500 })).toEqual({ min: 0, max: 5000 });
    expect(view.axisRange([[null], []])).toEqual({});
  });

  it('labels a point by its range and says what the row of values is', () => {
    expect(view.pointLabel(1700000000, '24h')).toMatch(/^\d{1,2}:\d{2}/);
    expect(view.pointLabel(1700000000, '30d')).toMatch(/\d{1,2}\/\d{1,2}/);
    expect(view.readingNote([SAMPLE], '24h')).toMatch(/^Stored reading from /);
    expect(view.readingNote([SAMPLE], '7d')).toMatch(/^Average of the 30 minutes up to /);
    expect(view.readingNote([SAMPLE], '30d')).toMatch(/^Average of the 120 minutes up to /);
    expect(view.readingNote([], '24h')).toBe('');
    expect(view.readingPills(null)).toEqual([]);
    expect(view.readingPills([{ cpu_temp: 1, cpu_util: 2, mem_pct: 3, disks: [{ name: 'sdq', temp: null, standby: false }, {}] }]).at(-1)).toEqual(['sdq', 'No reading', 'muted']);
  });

  it('takes the chart’s colours from the theme', () => {
    document.documentElement.style.setProperty('--fg', '#111111');
    document.documentElement.style.setProperty('--muted', '#444444');
    expect(view.chartColors()).toMatchObject({ text: '#111111', muted: '#444444' }); // fixed light greys: 1.4:1 in light mode
    document.documentElement.style.removeProperty('--fg');
    document.documentElement.style.removeProperty('--muted');
    expect(view.chartColors().text).toBe('#c9d6d7');
  });
});
