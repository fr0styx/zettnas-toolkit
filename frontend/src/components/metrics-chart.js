/**
 * ZettNAS Toolkit Historical Metrics Chart
 * Renders Chart.js line graphs for CPU temperature, utilization, and memory usage over time.
 */
import { api } from '../api.js';

let _metricsChart = null;
let _metricsRange = '24h';

export async function fetchAndRenderMetrics() {
  if (_metricsChart) _metricsChart.destroy();
  try {
    const data = await api.get(`/api/history?range=${_metricsRange}`);
    if (!data || data.length === 0) return;

    const labels = data.map((d) => {
      const dt = new Date(d.ts * 1000);
      if (_metricsRange === '24h') {
        return dt.getHours().toString().padStart(2, '0') + ':' + dt.getMinutes().toString().padStart(2, '0');
      } else {
        return (dt.getMonth() + 1) + '/' + dt.getDate() + ' ' + dt.getHours().toString().padStart(2, '0') + ':00';
      }
    });

    const cpuTemps = data.map((d) => d.cpu_temp);
    const cpuUtils = data.map((d) => d.cpu_util);
    const memPcts = data.map((d) => d.mem_pct);

    const canvas = document.getElementById('metricsChart');
    if (!canvas || typeof Chart === 'undefined') return;
    const ctx = canvas.getContext('2d');

    Chart.defaults.color = '#a0aec0';
    Chart.defaults.font.family = 'Inter, sans-serif';

    _metricsChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'CPU Temp (°C)',
            data: cpuTemps,
            borderColor: '#e74c3c',
            backgroundColor: 'rgba(231, 76, 60, 0.1)',
            borderWidth: 2,
            tension: 0.3,
            fill: true,
            pointRadius: 0
          },
          {
            label: 'CPU Util (%)',
            data: cpuUtils,
            borderColor: '#3498db',
            borderWidth: 2,
            tension: 0.3,
            pointRadius: 0
          },
          {
            label: 'Mem (%)',
            data: memPcts,
            borderColor: '#9b59b6',
            borderWidth: 2,
            tension: 0.3,
            pointRadius: 0
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 10, usePointStyle: true, font: { size: 10 } } }
        },
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { maxTicksLimit: 8 } },
          y: { grid: { color: 'rgba(255,255,255,0.05)' }, beginAtZero: true, max: 100 }
        }
      }
    });
  } catch (e) {
    console.error('Failed to load metrics history:', e);
  }
}

export function initMetricsChart() {
  const rs = document.getElementById('metrics-range-select');
  if (rs) {
    rs.addEventListener('change', (e) => {
      _metricsRange = e.target.value;
      fetchAndRenderMetrics();
    });
  }
}
