import { kbZoomPlugin } from './chart-zoom.js'; // replaces chartjs-plugin-zoom and hammerjs (ARC-15)
/**
 * Kiboto Historical Metrics Chart
 * Multi-device time-series telemetry for CPU, RAM, individual Disks, and Fans.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { formatFixed } from '../format.js';
import { showState } from './state-block.js';
import { REFRESH_MS, axisRange, chartColors, driveNames, driveSeries, fanSeries, pointLabel, readingNote, readingPills } from './metrics-view.js';

let _metricsChart = null;
let _metricsRange = '24h';
let _metricsGroup = 'all'; // 'all' | 'system' | 'disks' | 'fans'
let _cachedData = null;
let _ChartLib = null;
let _renderRequestId = 0;
let _refreshTimer = null;
let _zoomed = false;

const DISK_COLORS = [
  '#33cdb8', // teal
  '#46c776', // green
  '#f5a623', // amber
  '#a78bfa', // purple
  '#f87171', // red
  '#38bdf8', // sky
  '#fbbf24', // yellow
  '#ec4899', // pink
];

const FAN_COLORS = [
  '#33cdb8', // Fan 1 (Rear)
  '#46c776', // Fan 2 (Disks)
  '#f5a623', // Fan 3 (CPU)
];

async function getChart() {
  if (!_ChartLib) {
    const chartMod = await import('chart.js');
    const {
      Chart,
      LineController,
      LineElement,
      PointElement,
      LinearScale,
      CategoryScale,
      Legend,
      Tooltip,
      Filler
    } = chartMod;
    Chart.register(
      LineController,
      LineElement,
      PointElement,
      LinearScale,
      CategoryScale,
      Legend,
      Tooltip,
      Filler,
      kbZoomPlugin
    );
    _ChartLib = Chart;
  }
  return _ChartLib;
}

function formatRate(bytesSec) {
  if (bytesSec == null || isNaN(bytesSec) || bytesSec <= 0) return '0 B/s';
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
  let val = Number(bytesSec);
  let unitIdx = 0;
  while (val >= 1024 && unitIdx < units.length - 1) {
    val /= 1024;
    unitIdx++;
  }
  return `${formatFixed(val, unitIdx === 0 ? 0 : 1)} ${units[unitIdx]}`;
}

function updateSummaryStrip(data) {
  const strip = document.getElementById('metrics-device-summary-strip');
  if (!strip) return;
  if (!data || data.length === 0) {
    strip.replaceChildren();
    return;
  }
  const pill = (name, value, look = '') => {
    const el = document.createElement('div');
    el.className = 'device-metric-pill';
    const label = document.createElement('span');
    label.className = 'dmp-name';
    label.textContent = `${name}:`;
    const val = document.createElement('span');
    val.className = look ? `dmp-val is-${look}` : 'dmp-val';
    val.textContent = value;
    el.append(label, val);
    return el;
  };
  // the row is the last stored sample, not a live reading: it says which, and when
  const note = document.createElement('div');
  note.className = 'metrics-reading-note';
  note.textContent = readingNote(data, _metricsRange);
  const latest = data[data.length - 1];
  const pills = readingPills(data).map(([name, value, look]) => pill(name, value, look));
  pills.push(pill(t('mch.net_name', 'Network'), `↓ ${formatRate(latest.net_rx || 0)} · ↑ ${formatRate(latest.net_tx || 0)}`));
  if ((latest.disk_read || 0) > 0 || (latest.disk_write || 0) > 0) {
    pills.push(pill(t('mch.drive_io_name', 'Drive activity'), `R ${formatRate(latest.disk_read || 0)} · W ${formatRate(latest.disk_write || 0)}`));
  }
  strip.replaceChildren(note, ...pills);
}

/** The place for "loading", "nothing yet" and "could not load": the chart showed a blank area
 *  for all three, and an error went to the browser console only (SET-13). */
function say(canvas, kind, opts) {
  const frame = canvas.parentElement;
  if (!frame) return;
  let box = /** @type {HTMLElement | null} */ (frame.querySelector('.metrics-chart-state'));
  if (!box) {
    box = document.createElement('div');
    box.className = 'metrics-chart-state';
    frame.append(box);
  }
  box.hidden = !kind;
  canvas.hidden = Boolean(kind);
  if (kind) showState(box, kind, opts);
  else box.replaceChildren();
}

/** While the chart is on screen it is read again as new samples are stored; it was read once,
 *  when the page opened. Nothing is read once the page is closed. */
function keepFresh() {
  if (_refreshTimer) return;
  _refreshTimer = setInterval(() => {
    const canvas = document.getElementById('metricsChart');
    if (!canvas || !canvas.isConnected || canvas.offsetParent === null) {
      stopMetricsRefresh();
      return;
    }
    if (!document.hidden && !_zoomed) fetchAndRenderMetrics(false);
  }, REFRESH_MS);
}

/** Stops reading the chart again (the page went away). */
export function stopMetricsRefresh() {
  if (_refreshTimer) clearInterval(_refreshTimer);
  _refreshTimer = null;
}

export async function fetchAndRenderMetrics(skipFetch = false) {
  const reqId = ++_renderRequestId;
  if (_metricsChart) {
    _metricsChart.destroy();
    _metricsChart = null;
  }
  const canvas = /** @type {HTMLCanvasElement | null} */ (document.getElementById('metricsChart'));
  if (!canvas) return;

  try {
    if (!skipFetch || !_cachedData) {
      if (!_cachedData) say(canvas, 'loading');
      _cachedData = await api.get(`/api/history?range=${_metricsRange}`);
    }
  } catch (e) {
    if (reqId !== _renderRequestId) return;
    _cachedData = null;
    updateSummaryStrip(null);
    say(canvas, 'failed', { text: t('mch.failed', 'The history could not be loaded.'), detail: e instanceof Error ? e.message : '', retry: () => fetchAndRenderMetrics(false) });
    return;
  }

  try {
    if (reqId !== _renderRequestId) return;
    const data = _cachedData;
    updateSummaryStrip(data);
    if (!data || data.length === 0) {
      say(canvas, 'empty', { text: t('mch.empty', 'No history yet. The first reading is stored five minutes after Kiboto starts.') });
      keepFresh();
      return;
    }
    say(canvas, null);
    keepFresh();

    const Chart = await getChart();
    if (!Chart || reqId !== _renderRequestId) return;

    const colors = chartColors(); // from the theme: fixed light greys could not be read in light mode
    const labels = data.map((d) => pointLabel(d.ts, _metricsRange));

    const datasets = [];
    const scales = {
      x: { grid: { color: colors.grid }, ticks: { maxTicksLimit: 8 } },
      y: {
        grid: { color: colors.grid },
        beginAtZero: true,
        title: { display: true, text: t('mch.util_temp', 'Utilization (%) / Temp (°C)'), font: { size: 11 }, color: colors.muted }
      }
    };

    if (_metricsGroup === 'system') {
      datasets.push({
        label: t('mch.cpu_temp', 'CPU Temp (°C)'),
        data: data.map((d) => d.cpu_temp),
        borderColor: '#f87171',
        backgroundColor: 'rgba(248, 113, 113, 0.12)',
        borderWidth: 2,
        tension: 0.3,
        fill: true,
        pointRadius: 0,
        pointHoverRadius: 4
      });
      datasets.push({
        label: t('mch.cpu_util', 'CPU Util (%)'),
        data: data.map((d) => d.cpu_util),
        borderColor: '#4fd8c4',
        backgroundColor: 'rgba(79, 216, 196, 0.08)',
        borderWidth: 2,
        tension: 0.3,
        fill: false,
        pointRadius: 0,
        pointHoverRadius: 4
      });
      datasets.push({
        label: t('mch.memory', 'Memory (%)'),
        data: data.map((d) => d.mem_pct),
        borderColor: '#a78bfa',
        backgroundColor: 'rgba(167, 139, 250, 0.08)',
        borderWidth: 2,
        tension: 0.3,
        fill: false,
        pointRadius: 0,
        pointHoverRadius: 4
      });
      scales.y.max = 100;
    } else if (_metricsGroup === 'disks') {
      const temps = driveNames(data).map((name) => driveSeries(data, name));
      driveNames(data).forEach((diskName, idx) => {
        datasets.push({
          label: `${diskName} (°C)`,
          data: temps[idx],
          borderColor: DISK_COLORS[idx % DISK_COLORS.length],
          backgroundColor: 'transparent',
          borderWidth: 2,
          tension: 0.3,
          spanGaps: false, // a drive that slept has a gap, not a line through it
          pointRadius: 0,
          pointHoverRadius: 4
        });
      });

      scales.y.title.text = t('mch.temp_axis', 'Temperature (°C)');
      scales.y.beginAtZero = false;
      Object.assign(scales.y, axisRange(temps, { floor: 20, step: 5 }));
    } else if (_metricsGroup === 'fans') {
      // as many fans as this machine reports, by number: the names assumed three fans in fixed places
      const fans = fanSeries(data);
      fans.forEach((fan, f) => {
        datasets.push({
          label: `${fan.label} (RPM)`,
          data: fan.data,
          borderColor: FAN_COLORS[f % FAN_COLORS.length],
          backgroundColor: 'transparent',
          borderWidth: 2,
          tension: 0.3,
          spanGaps: false,
          pointRadius: 0,
          pointHoverRadius: 4
        });
      });

      scales.y.title.text = t('mch.speed_axis', 'Speed (RPM)');
      Object.assign(scales.y, axisRange(fans.map((fan) => fan.data), { floor: 0, step: 500 }));
    } else if (_metricsGroup === 'network') {
      const maxNet = Math.max(...data.map((d) => Math.max(d.net_rx || 0, d.net_tx || 0)), 0);
      const useMB = maxNet >= 1024 * 1024;
      const factor = useMB ? (1024 * 1024) : 1024;
      const unitStr = useMB ? 'MB/s' : 'KB/s';

      datasets.push({
        label: t('mch.rx', 'Download Rx ({unit})', { unit: unitStr }),
        data: data.map((d) => Number(((d.net_rx || 0) / factor).toFixed(2))),
        borderColor: '#4fd8c4',
        backgroundColor: 'rgba(79, 216, 196, 0.15)',
        borderWidth: 2,
        tension: 0.3,
        fill: true,
        pointRadius: 0,
        pointHoverRadius: 4
      });

      datasets.push({
        label: t('mch.tx', 'Upload Tx ({unit})', { unit: unitStr }),
        data: data.map((d) => Number(((d.net_tx || 0) / factor).toFixed(2))),
        borderColor: '#a78bfa',
        backgroundColor: 'rgba(167, 139, 250, 0.15)',
        borderWidth: 2,
        tension: 0.3,
        fill: true,
        pointRadius: 0,
        pointHoverRadius: 4
      });

      const maxDisk = Math.max(...data.map((d) => Math.max(d.disk_read || 0, d.disk_write || 0)), 0);
      if (maxDisk > 0) {
        datasets.push({
          label: t('mch.read', 'Disk Read ({unit})', { unit: unitStr }),
          data: data.map((d) => Number(((d.disk_read || 0) / factor).toFixed(2))),
          borderColor: '#33cdb8',
          borderDash: [3, 3],
          borderWidth: 1.5,
          tension: 0.3,
          fill: false,
          pointRadius: 0,
          pointHoverRadius: 4
        });
        datasets.push({
          label: t('mch.write', 'Disk Write ({unit})', { unit: unitStr }),
          data: data.map((d) => Number(((d.disk_write || 0) / factor).toFixed(2))),
          borderColor: '#f5a623',
          borderDash: [3, 3],
          borderWidth: 1.5,
          tension: 0.3,
          fill: false,
          pointRadius: 0,
          pointHoverRadius: 4
        });
      }

      scales.y.title.text = t('mch.rate_axis', 'Throughput ({unit})', { unit: unitStr });
      scales.y.beginAtZero = true;
    } else {
      // 'all' view: CPU, RAM, Disk Temps (clean single 0-100 scale, no conflicting fan RPM axis)
      datasets.push({
        label: t('mch.cpu_temp', 'CPU Temp (°C)'),
        data: data.map((d) => d.cpu_temp),
        borderColor: '#f87171',
        backgroundColor: 'rgba(248, 113, 113, 0.1)',
        borderWidth: 2,
        tension: 0.3,
        fill: false,
        pointRadius: 0,
        pointHoverRadius: 4
      });
      datasets.push({
        label: t('mch.cpu_util', 'CPU Util (%)'),
        data: data.map((d) => d.cpu_util),
        borderColor: '#4fd8c4',
        borderWidth: 1.5,
        tension: 0.3,
        pointRadius: 0
      });
      datasets.push({
        label: t('mch.memory', 'Memory (%)'),
        data: data.map((d) => d.mem_pct),
        borderColor: '#a78bfa',
        borderWidth: 1.5,
        tension: 0.3,
        pointRadius: 0
      });

      // each drive's line in the 'all' view
      driveNames(data).forEach((diskName, idx) => {
        datasets.push({
          label: `${diskName} (°C)`,
          data: driveSeries(data, diskName),
          borderColor: DISK_COLORS[idx % DISK_COLORS.length],
          backgroundColor: 'transparent',
          borderWidth: 1.5,
          tension: 0.3,
          spanGaps: false,
          pointRadius: 0,
          pointHoverRadius: 4
        });
      });

      scales.y.max = 100;
    }

    if (reqId !== _renderRequestId) return;
    if (_metricsChart) {
      _metricsChart.destroy();
      _metricsChart = null;
    }
    const existingChart = Chart.getChart ? Chart.getChart(canvas) : null;
    if (existingChart) {
      existingChart.destroy();
    }

    const ctx = canvas.getContext('2d');
    Chart.defaults.color = colors.muted;
    Chart.defaults.font.family = 'Inter, sans-serif';

    _metricsChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            position: 'top',
            labels: { boxWidth: 10, usePointStyle: true, font: { size: 11 }, color: colors.text }
          },
          tooltip: {
            backgroundColor: colors.panel,
            titleColor: colors.text,
            bodyColor: colors.text,
            borderColor: colors.grid,
            borderWidth: 1,
            padding: 10,
            cornerRadius: 8
          },
          kbZoom: {
            wheelSpeed: 0.08,
            onChange: (_chart, zoomed) => {
              _zoomed = Boolean(zoomed); // a zoomed chart is not read again under the reader
              const resetBtn = document.getElementById('metrics-reset-zoom-btn');
              if (resetBtn) resetBtn.style.display = zoomed ? 'inline-flex' : 'none';
            }
          }
        },
        scales
      }
    });

    _zoomed = false;
    const resetBtn = document.getElementById('metrics-reset-zoom-btn');
    if (resetBtn) resetBtn.style.display = 'none';
  } catch (e) {
    console.error('Failed to draw the history chart:', e);
    say(canvas, 'failed', { text: t('mch.failed', 'The history could not be loaded.'), detail: e instanceof Error ? e.message : '', retry: () => fetchAndRenderMetrics(false) });
  }
}

let _wired = false;

/** Opens the history page: wires its controls once, then draws the chart. */
export function showMetricsPage() {
  if (!_wired) {
    _wired = true;
    initMetricsChart();
  }
  return fetchAndRenderMetrics();
}

export function initMetricsChart() {
  const rs = document.getElementById('metrics-range-select');
  if (rs) {
    rs.addEventListener('change', (e) => {
      _metricsRange = e.target.value;
      fetchAndRenderMetrics(false);
    });
  }

  // Reset Zoom Button
  const resetBtn = document.getElementById('metrics-reset-zoom-btn');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      if (_metricsChart && typeof _metricsChart.resetZoom === 'function') {
        _metricsChart.resetZoom();
        _zoomed = false;
        resetBtn.style.display = 'none';
      }
    });
  }

  // Device category filter buttons
  document.querySelectorAll('.metrics-device-btn').forEach((btn) => {
    btn.setAttribute('aria-pressed', String(btn.classList.contains('active')));
    btn.addEventListener('click', () => {
      document.querySelectorAll('.metrics-device-btn').forEach((b) => {
        b.classList.toggle('active', b === btn);
        b.setAttribute('aria-pressed', String(b === btn)); // the chosen group was shown by colour only
      });
      _metricsGroup = btn.dataset.metricGroup || 'all';
      fetchAndRenderMetrics(true); // Re-use cached history data for instant tab switching
    });
  });

  // Re-render chart on language switch to update localized labels
  window.addEventListener('kiboto:lang-changed', () => {
    if (_cachedData) fetchAndRenderMetrics(true); // the row of values and the states too, not only a drawn chart
  });
}

