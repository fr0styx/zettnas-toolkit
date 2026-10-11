import { describe, it, expect, beforeEach, vi } from 'vitest';
import { initMetricsChart, fetchAndRenderMetrics } from '../components/metrics-chart.js';
import { api } from '../api.js';

vi.mock('../api.js', () => ({
  api: {
    get: vi.fn()
  }
}));

describe('Historical Metrics Chart & Summary Strip Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <select id="metrics-range-select">
        <option value="1h">1h</option>
        <option value="24h" selected>24h</option>
        <option value="7d">7d</option>
      </select>
      <button id="metrics-reset-zoom-btn" style="display:none;">Reset Zoom</button>

      <div class="metrics-device-filter-row">
        <button class="metrics-device-btn active" data-metric-group="all">All</button>
        <button class="metrics-device-btn" data-metric-group="system">CPU & RAM</button>
        <button class="metrics-device-btn" data-metric-group="disks">Storage Disks</button>
        <button class="metrics-device-btn" data-metric-group="network">Network Bandwidth</button>
        <button class="metrics-device-btn" data-metric-group="fans">Cooling Fans</button>
      </div>

      <div id="metrics-device-summary-strip"></div>
      <canvas id="metricsChart"></canvas>
    `;
  });

  it('renders summary strip with CPU, RAM, Disks, Fans, Net throughput and Disk I/O', async () => {
    const mockHistoryData = [
      {
        ts: 1700000000,
        cpu_temp: 45,
        cpu_util: 12,
        mem_pct: 38,
        net_rx: 1548576, // ~1.5 MB/s
        net_tx: 524288,  // 512 KB/s
        disk_read: 2097152, // 2.0 MB/s
        disk_write: 1048576, // 1.0 MB/s
        disks: [
          { name: 'sda', temp: 34, standby: false },
          { name: 'sdb', temp: null, standby: true }
        ],
        fans: [950, 1100, 1850]
      }
    ];

    api.get.mockResolvedValue(mockHistoryData);

    await fetchAndRenderMetrics(false);

    const strip = document.getElementById('metrics-device-summary-strip');
    expect(strip).toBeTruthy();
    const text = strip.textContent;

    // CPU and RAM
    expect(text).toContain('CPU:');
    expect(text).toContain('45°C (12%)');
    expect(text).toContain('RAM:');
    expect(text).toContain('38%');

    // Disks (active and standby)
    expect(text).toContain('sda:');
    expect(text).toContain('34°C');
    expect(text).toContain('sdb:');
    expect(text).toContain('Standby');

    // Fans
    expect(text).toContain('Rear Fan:');
    expect(text).toContain('950 RPM');
    expect(text).toContain('Drive Bay Fan:');
    expect(text).toContain('1100 RPM');
    expect(text).toContain('CPU Fan:');
    expect(text).toContain('1850 RPM');

    // Network Bandwidth Throughput
    expect(text).toContain('Net:');
    expect(text).toContain('↓ 1.5 MB/s');
    expect(text).toContain('↑ 512.0 KB/s');

    // Disk I/O Throughput
    expect(text).toContain('Disk I/O:');
    expect(text).toContain('R: 2.0 MB/s');
    expect(text).toContain('W: 1.0 MB/s');
  });

  it('switches metric filter button active state on click', () => {
    initMetricsChart();

    const allBtn = document.querySelector('button[data-metric-group="all"]');
    const netBtn = document.querySelector('button[data-metric-group="network"]');

    expect(allBtn.classList.contains('active')).toBe(true);
    expect(netBtn.classList.contains('active')).toBe(false);

    netBtn.click();

    expect(allBtn.classList.contains('active')).toBe(false);
    expect(netBtn.classList.contains('active')).toBe(true);
  });
});
