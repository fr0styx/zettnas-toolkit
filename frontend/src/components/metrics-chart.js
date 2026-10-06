import { escapeHtml } from '../utils.js';
/**
 * ZettNAS Toolkit Historical Metrics Chart
 * Multi-device time-series telemetry for CPU, RAM, individual Disks, and Fans.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';

let _metricsChart = null;
let _metricsRange = '24h';
let _metricsGroup = 'all'; // 'all' | 'system' | 'disks' | 'fans'
let _cachedData = null;
let _ChartLib = null;
let _renderRequestId = 0;

const DISK_COLORS = [
  '#00f0ff', // cyan
  '#25c2a0', // teal
  '#f5a623', // amber
  '#a78bfa', // purple
  '#f87171', // red
  '#38bdf8', // sky
  '#fbbf24', // yellow
  '#ec4899', // pink
];

const FAN_COLORS = [
  '#00f0ff', // Fan 1 (Rear)
  '#25c2a0', // Fan 2 (Disks)
  '#f5a623', // Fan 3 (CPU)
];

async function getChart() {
  if (!_ChartLib) {
    const [chartMod, zoomPluginMod] = await Promise.all([
      import('chart.js/auto'),
      import('chartjs-plugin-zoom')
    ]);
    const Chart = chartMod.default || chartMod;
    const zoomPlugin = zoomPluginMod.default || zoomPluginMod;
    Chart.register(zoomPlugin);
    _ChartLib = Chart;
  }
  return _ChartLib;
}

function updateSummaryStrip(data) {
  const strip = document.getElementById('metrics-device-summary-strip');
  if (!strip || !data || data.length === 0) return;

  const latest = data[data.length - 1];
  const pills = [];

  // CPU Pill
  pills.push(`
    <div class="device-metric-pill">
      <span class="dmp-name">CPU:</span>
      <span class="dmp-val">${latest.cpu_temp}°C (${latest.cpu_util}%)</span>
    </div>
  `);

  // RAM Pill
  pills.push(`
    <div class="device-metric-pill">
      <span class="dmp-name">RAM:</span>
      <span class="dmp-val">${latest.mem_pct}%</span>
    </div>
  `);

  // Disks Pills
  if (latest.disks && Array.isArray(latest.disks)) {
    latest.disks.forEach((d) => {
      const tempStr = d.temp != null ? `${d.temp}°C` : (d.standby ? 'Standby' : '--');
      const tempColor = d.temp != null && d.temp > 50 ? 'var(--crit)' : d.standby ? 'var(--muted)' : 'var(--ok2)';
      pills.push(`
        <div class="device-metric-pill">
          <span class="dmp-name">${escapeHtml(d.name)}:</span>
          <span class="dmp-val" style="color:${tempColor};">${tempStr}</span>
        </div>
      `);
    });
  }

  // Fans Pills
  if (latest.fans && Array.isArray(latest.fans)) {
    latest.fans.forEach((rpm, idx) => {
      const fanNames = ['Rear Fan', 'Drive Bay Fan', 'CPU Fan'];
      const name = fanNames[idx] || `Fan ${idx + 1}`;
      pills.push(`
        <div class="device-metric-pill">
          <span class="dmp-name">${name}:</span>
          <span class="dmp-val">${rpm} RPM</span>
        </div>
      `);
    });
  }

  strip.innerHTML = pills.join('');
}

export async function fetchAndRenderMetrics(skipFetch = false) {
  const reqId = ++_renderRequestId;
  if (_metricsChart) {
    _metricsChart.destroy();
    _metricsChart = null;
  }

  try {
    const canvas = document.getElementById('metricsChart');
    if (!canvas) return;

    if (!skipFetch || !_cachedData) {
      _cachedData = await api.get(`/api/history?range=${_metricsRange}`);
    }
    if (reqId !== _renderRequestId) return;
    const data = _cachedData;
    if (!data || data.length === 0) return;

    updateSummaryStrip(data);

    const Chart = await getChart();
    if (!Chart || reqId !== _renderRequestId) return;

    const labels = data.map((d) => {
      const dt = new Date(d.ts * 1000);
      if (_metricsRange === '1h' || _metricsRange === '6h' || _metricsRange === '24h') {
        return dt.getHours().toString().padStart(2, '0') + ':' + dt.getMinutes().toString().padStart(2, '0');
      } else {
        return (dt.getMonth() + 1) + '/' + dt.getDate() + ' ' + dt.getHours().toString().padStart(2, '0') + ':00';
      }
    });

    const datasets = [];
    const scales = {
      x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { maxTicksLimit: 8 } },
      y: {
        grid: { color: 'rgba(255,255,255,0.05)' },
        beginAtZero: true,
        title: { display: true, text: 'Utilization (%) / Temp (°C)', font: { size: 9 }, color: '#94a3b8' }
      }
    };

    if (_metricsGroup === 'system') {
      datasets.push({
        label: 'CPU Temp (°C)',
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
        label: 'CPU Util (%)',
        data: data.map((d) => d.cpu_util),
        borderColor: '#38bdf8',
        backgroundColor: 'rgba(56, 189, 248, 0.08)',
        borderWidth: 2,
        tension: 0.3,
        fill: false,
        pointRadius: 0,
        pointHoverRadius: 4
      });
      datasets.push({
        label: 'Memory (%)',
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
      // Find all unique disk names across data
      const diskNames = new Set();
      data.forEach((d) => {
        if (d.disks && Array.isArray(d.disks)) {
          d.disks.forEach((disk) => {
            if (disk.name) diskNames.add(disk.name);
          });
        }
      });

      const sortedDisks = Array.from(diskNames).sort();
      sortedDisks.forEach((diskName, idx) => {
        const color = DISK_COLORS[idx % DISK_COLORS.length];
        const diskTemps = data.map((d) => {
          if (!d.disks) return null;
          const match = d.disks.find((x) => x.name === diskName);
          return match && match.temp != null ? match.temp : null;
        });

        datasets.push({
          label: `${diskName.toUpperCase()} (°C)`,
          data: diskTemps,
          borderColor: color,
          backgroundColor: 'transparent',
          borderWidth: 2,
          tension: 0.3,
          spanGaps: true,
          pointRadius: 0,
          pointHoverRadius: 4
        });
      });

      scales.y.title.text = 'Temperature (°C)';
      scales.y.min = 15;
      scales.y.max = 65;
    } else if (_metricsGroup === 'fans') {
      const fanNames = ['Rear / Exhaust Fan', 'Drive Bay Fan', 'CPU Cooler Fan'];
      const maxFans = Math.max(...data.map((d) => (d.fans ? d.fans.length : 0)), 1);

      for (let f = 0; f < maxFans; f++) {
        const color = FAN_COLORS[f % FAN_COLORS.length] || '#00f0ff';
        const label = fanNames[f] || `Fan ${f + 1}`;
        const fanSpeeds = data.map((d) => (d.fans && d.fans[f] != null ? d.fans[f] : null));

        datasets.push({
          label: `${label} (RPM)`,
          data: fanSpeeds,
          borderColor: color,
          backgroundColor: 'transparent',
          borderWidth: 2,
          tension: 0.3,
          spanGaps: true,
          pointRadius: 0,
          pointHoverRadius: 4
        });
      }

      scales.y.title.text = 'Speed (RPM)';
      scales.y.min = 0;
      scales.y.max = 3500;
    } else {
      // 'all' view: CPU, RAM, Disk Temps, and Dual Axis for Fans
      datasets.push({
        label: 'CPU Temp (°C)',
        data: data.map((d) => d.cpu_temp),
        borderColor: '#f87171',
        backgroundColor: 'rgba(248, 113, 113, 0.1)',
        borderWidth: 2,
        tension: 0.3,
        fill: false,
        pointRadius: 0,
        pointHoverRadius: 4,
        yAxisID: 'y'
      });
      datasets.push({
        label: 'CPU (%)',
        data: data.map((d) => d.cpu_util),
        borderColor: '#38bdf8',
        borderWidth: 1.5,
        tension: 0.3,
        pointRadius: 0,
        yAxisID: 'y'
      });
      datasets.push({
        label: 'RAM (%)',
        data: data.map((d) => d.mem_pct),
        borderColor: '#a78bfa',
        borderWidth: 1.5,
        tension: 0.3,
        pointRadius: 0,
        yAxisID: 'y'
      });

      // Individual Disk lines in 'all' view
      const diskNames = new Set();
      data.forEach((d) => {
        if (d.disks && Array.isArray(d.disks)) {
          d.disks.forEach((disk) => {
            if (disk.name) diskNames.add(disk.name);
          });
        }
      });
      const sortedDisks = Array.from(diskNames).sort();
      sortedDisks.forEach((diskName, idx) => {
        const color = DISK_COLORS[idx % DISK_COLORS.length];
        const diskTemps = data.map((d) => {
          if (!d.disks) return null;
          const match = d.disks.find((x) => x.name === diskName);
          return match && match.temp != null ? match.temp : null;
        });

        datasets.push({
          label: `${diskName} (°C)`,
          data: diskTemps,
          borderColor: color,
          backgroundColor: 'transparent',
          borderWidth: 1.5,
          tension: 0.3,
          spanGaps: true,
          pointRadius: 0,
          pointHoverRadius: 4,
          yAxisID: 'y'
        });
      });

      // Fans on y1 (right axis)
      const maxFans = Math.max(...data.map((d) => (d.fans ? d.fans.length : 0)), 0);
      const fanNames = ['Rear Fan', 'Disks Fan', 'CPU Fan'];
      for (let f = 0; f < maxFans; f++) {
        const label = fanNames[f] || `Fan ${f + 1}`;
        datasets.push({
          label: `${label} (RPM)`,
          data: data.map((d) => (d.fans && d.fans[f] != null ? d.fans[f] : null)),
          borderColor: FAN_COLORS[f % FAN_COLORS.length],
          borderDash: [4, 4],
          borderWidth: 1.5,
          tension: 0.3,
          spanGaps: true,
          pointRadius: 0,
          pointHoverRadius: 4,
          yAxisID: 'y1'
        });
      }

      scales.y.max = 100;
      scales.y1 = {
        position: 'right',
        beginAtZero: true,
        max: 3500,
        grid: { display: false },
        title: { display: true, text: 'Fan RPM', font: { size: 9 }, color: '#94a3b8' },
        ticks: { color: '#94a3b8', font: { size: 9 } }
      };
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
    Chart.defaults.color = '#a0aec0';
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
            labels: { boxWidth: 10, usePointStyle: true, font: { size: 10 }, color: '#cbd5e1' }
          },
          tooltip: {
            backgroundColor: 'rgba(13, 20, 30, 0.95)',
            borderColor: 'rgba(255, 255, 255, 0.15)',
            borderWidth: 1,
            padding: 10,
            cornerRadius: 8
          },
          zoom: {
            pan: {
              enabled: true,
              mode: 'x',
              threshold: 5,
              onPanComplete: () => {
                const resetBtn = document.getElementById('metrics-reset-zoom-btn');
                if (resetBtn) resetBtn.style.display = 'inline-flex';
              }
            },
            zoom: {
              wheel: {
                enabled: true,
                speed: 0.08
              },
              pinch: {
                enabled: true
              },
              mode: 'x',
              onZoomComplete: () => {
                const resetBtn = document.getElementById('metrics-reset-zoom-btn');
                if (resetBtn) resetBtn.style.display = 'inline-flex';
              }
            }
          }
        },
        scales
      }
    });

    const resetBtn = document.getElementById('metrics-reset-zoom-btn');
    if (resetBtn) resetBtn.style.display = 'none';
  } catch (e) {
    console.error('Failed to load metrics history:', e);
  }
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
        resetBtn.style.display = 'none';
      }
    });
  }

  // Device category filter buttons
  document.querySelectorAll('.metrics-device-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.metrics-device-btn').forEach((b) => b.classList.toggle('active', b === btn));
      _metricsGroup = btn.dataset.metricGroup || 'all';
      fetchAndRenderMetrics(true); // Re-use cached history data for instant tab switching
    });
  });

  // Re-render chart on language switch to update localized labels
  window.addEventListener('zettnas:lang-changed', () => {
    if (_metricsChart) {
      fetchAndRenderMetrics(true);
    }
  });
}

