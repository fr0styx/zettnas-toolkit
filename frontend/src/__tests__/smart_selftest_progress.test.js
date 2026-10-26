import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  renderSelfTestLog,
  renderSmartLatestReport,
  switchSmartTab,
  updateSmartTestProgressUI,
  generateSmartReportMarkdown,
  copySmartReport,
  startSmartPolling,
  stopSmartPolling
} from '../modals.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

describe('S.M.A.R.T. Self-Test Progress & Historical Report Suite', () => {
  let container;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});

    container = document.createElement('div');
    container.innerHTML = `
      <div id="smart-modal-overlay" class="smart-modal-backdrop open">
        <div id="smart-nav-tabs" class="smart-nav-tabs">
          <button class="smart-tab-btn active" data-tab="health">Health &amp; Telemetry</button>
          <button class="smart-tab-btn" data-tab="selftest">Self-Test &amp; Reports</button>
          <button class="smart-tab-btn" data-tab="raw">Raw Telemetry</button>
        </div>

        <div id="smart-actions-container">
          <button id="smart-btn-short-test">Short Test</button>
          <button id="smart-btn-extended-test">Extended Test</button>
          <button id="smart-btn-abort-test" style="display: none;">Abort Test</button>
          <span id="smart-test-status"></span>
        </div>

        <div id="smart-pane-health" class="smart-pane active"></div>

        <div id="smart-pane-selftest" class="smart-pane">
          <div id="smart-progress-card" class="smart-progress-card" style="display: none;">
            <span class="smart-progress-pulse-dot" id="smart-progress-pulse"></span>
            <span id="smart-progress-status-desc" class="smart-progress-status-desc"></span>
            <span id="smart-progress-pct-label" class="smart-progress-pct-label">0%</span>
            <span id="smart-progress-eta" class="smart-progress-eta" style="display: none;"></span>
            <div class="smart-progress-track">
              <div id="smart-progress-bar" class="smart-progress-bar" style="width: 0%;"></div>
            </div>
          </div>

          <div id="smart-latest-report-card" class="smart-report-card" style="display: none;">
            <div id="smart-report-badge"></div>
            <div id="smart-report-meta"></div>
            <div id="smart-report-lba"></div>
            <div id="smart-report-temp"></div>
            <div id="smart-report-hours"></div>
            <div id="smart-report-type"></div>
            <div id="smart-report-recommendation"></div>
          </div>

          <div id="smart-empty-hero" class="smart-empty-hero" style="display: none;"></div>

          <div id="smart-test-history-card">
            <span id="smart-test-count-badge">0</span>
            <button id="smart-btn-copy-report">
              <span id="smart-copy-report-icon">📋</span>
              <span id="smart-copy-report-label">Copy Report</span>
            </button>
            <table id="smart-test-history-table">
              <tbody id="smart-test-history-tbody"></tbody>
            </table>
            <div id="smart-test-history-empty" style="display: none;">No records</div>
          </div>
        </div>

        <div id="smart-pane-raw" class="smart-pane">
          <input id="smart-raw-filter" />
          <pre id="smart-raw-output"></pre>
        </div>
      </div>
    `;
    document.body.appendChild(container);
  });

  afterEach(() => {
    stopSmartPolling();
    vi.clearAllTimers();
    vi.useRealTimers();
    container?.remove();
    vi.restoreAllMocks();
  });

  describe('renderSelfTestLog', () => {
    it('handles empty or null logs gracefully with empty placeholder', () => {
      renderSelfTestLog(null);
      const tbody = document.getElementById('smart-test-history-tbody');
      const empty = document.getElementById('smart-test-history-empty');
      const badge = document.getElementById('smart-test-count-badge');

      expect(tbody.children.length).toBe(0);
      expect(empty.style.display).toBe('block');
      expect(badge.textContent).toBe('0');
    });

    it('renders historical self-test entries with status pills and formatted metrics', () => {
      const mockLog = [
        {
          num: 1,
          type: 'Short offline',
          status: 'Completed without error',
          passed: true,
          lifetime_hours: 2231,
          remaining_pct: 0,
          lba_first_error: '-'
        },
        {
          num: 2,
          type: 'Extended offline',
          status: 'Aborted by host',
          passed: false,
          lifetime_hours: 1540,
          remaining_pct: 70,
          lba_first_error: '-'
        },
        {
          num: 3,
          type: 'Short offline',
          status: 'Completed: read failure',
          passed: false,
          lifetime_hours: 950,
          remaining_pct: 10,
          lba_first_error: '194582910'
        }
      ];

      renderSelfTestLog(mockLog);

      const tbody = document.getElementById('smart-test-history-tbody');
      const empty = document.getElementById('smart-test-history-empty');
      const badge = document.getElementById('smart-test-count-badge');

      expect(empty.style.display).toBe('none');
      expect(badge.textContent).toBe('3');
      expect(tbody.children.length).toBe(3);

      const row1 = tbody.children[0];
      expect(row1.innerHTML).toContain('#1');
      expect(row1.innerHTML).toContain('Short offline');
      expect(row1.innerHTML).toContain('smart-test-status-passed');
      expect(row1.innerHTML).toContain('2,231 h');

      const row2 = tbody.children[1];
      expect(row2.innerHTML).toContain('#2');
      expect(row2.innerHTML).toContain('smart-test-status-aborted');

      const row3 = tbody.children[2];
      expect(row3.innerHTML).toContain('#3');
      expect(row3.innerHTML).toContain('smart-test-status-failed');
      expect(row3.innerHTML).toContain('194582910');
    });
  });

  describe('updateSmartTestProgressUI', () => {
    it('activates progress card and disables test buttons when test is in progress', () => {
      const data = {
        self_test_progress: {
          in_progress: true,
          percent_completed: 45,
          percent_remaining: 55,
          status_text: 'Self-test in progress, 55% remaining',
          polling_minutes: { short: 2, extended: 90 }
        }
      };

      updateSmartTestProgressUI(data, 'short');

      const card = document.getElementById('smart-progress-card');
      const bar = document.getElementById('smart-progress-bar');
      const pct = document.getElementById('smart-progress-pct-label');
      const desc = document.getElementById('smart-progress-status-desc');
      const eta = document.getElementById('smart-progress-eta');
      const shortBtn = document.getElementById('smart-btn-short-test');
      const extBtn = document.getElementById('smart-btn-extended-test');
      const abortBtn = document.getElementById('smart-btn-abort-test');

      expect(card.style.display).toBe('flex');
      expect(bar.style.width).toBe('45%');
      expect(pct.textContent).toBe('45%');
      expect(desc.textContent).toBe('Self-test in progress, 55% remaining');
      expect(eta.style.display).toBe('inline');
      expect(eta.textContent).toBe('~2 min est.');
      expect(shortBtn.disabled).toBe(true);
      expect(extBtn.disabled).toBe(true);
      expect(abortBtn.style.display).toBe('inline-block');
    });

    it('renders aborted state correctly and re-enables buttons', () => {
      const data = {
        self_test_progress: {
          in_progress: false,
          is_aborted: true,
          percent_completed: 100
        }
      };

      updateSmartTestProgressUI(data);

      const card = document.getElementById('smart-progress-card');
      const bar = document.getElementById('smart-progress-bar');
      const pct = document.getElementById('smart-progress-pct-label');
      const shortBtn = document.getElementById('smart-btn-short-test');
      const abortBtn = document.getElementById('smart-btn-abort-test');

      expect(card.style.display).toBe('flex');
      expect(bar.style.width).toBe('100%');
      expect(pct.textContent).toBe('Aborted');
      expect(shortBtn.disabled).toBe(false);
      expect(abortBtn.style.display).toBe('none');
    });
  });

  describe('generateSmartReportMarkdown', () => {
    it('generates well-formatted Markdown with drive telemetry and test log table', () => {
      const mockDiskData = {
        dev: 'sdb',
        model: 'ST22000NM001E-3HL103',
        serial: 'ZR500ABC',
        health: 'PASSED',
        temp: 34,
        power_on_hours: 2240,
        self_test_status: 'Completed without error',
        degradation: {
          status: 'optimal',
          realloc_7d_delta: 0,
          recommendation: 'Drive operating within safe nominal tolerances.'
        },
        self_test_log: [
          {
            num: 1,
            type: 'Short offline',
            status: 'Completed without error',
            passed: true,
            lifetime_hours: 2240,
            lba_first_error: '-'
          }
        ]
      };

      const md = generateSmartReportMarkdown(mockDiskData);

      expect(md).toContain('# S.M.A.R.T. Diagnostic Report: /dev/sdb');
      expect(md).toContain('ST22000NM001E-3HL103');
      expect(md).toContain('ZR500ABC');
      expect(md).toContain('**PASSED**');
      expect(md).toContain('34°C');
      expect(md).toContain('2240 hrs');
      expect(md).toContain('## SMART Velocity & Degradation Analysis');
      expect(md).toContain('## Self-Test Results History (1 Records)');
      expect(md).toContain('| 1 | Short offline | Completed without error | 2240 h | - |');
    });
  });

  describe('startSmartPolling & stopSmartPolling', () => {
    it('polls /api/disk_detail every 3000ms and automatically terminates when self-test completes', async () => {
      let callCount = 0;
      vi.spyOn(api, 'request').mockImplementation(async () => {
        callCount++;
        if (callCount === 1) {
          return {
            ok: true,
            json: async () => ({
              dev: 'sdb',
              self_test_progress: {
                in_progress: true,
                percent_completed: 60,
                percent_remaining: 40,
                status_text: 'Self-test in progress, 40% remaining'
              },
              self_test_log: []
            })
          };
        } else {
          return {
            ok: true,
            json: async () => ({
              dev: 'sdb',
              self_test_progress: {
                in_progress: false,
                percent_completed: 100,
                percent_remaining: 0,
                status_text: 'completed without error'
              },
              self_test_log: [
                {
                  num: 1,
                  type: 'Short offline',
                  status: 'Completed without error',
                  passed: true,
                  lifetime_hours: 2240,
                  lba_first_error: '-'
                }
              ]
            })
          };
        }
      });

      // Start polling
      startSmartPolling('sdb', 'short');

      // Tick 1 (3000ms)
      await vi.advanceTimersByTimeAsync(3000);
      expect(api.request).toHaveBeenCalledTimes(1);

      const bar = document.getElementById('smart-progress-bar');
      expect(bar.style.width).toBe('60%');

      // Tick 2 (6000ms): test finishes
      await vi.advanceTimersByTimeAsync(3000);
      expect(api.request).toHaveBeenCalledTimes(2);

      // Should have shown toast and stopped polling
      expect(toast.showToast).toHaveBeenCalledWith(
        expect.stringContaining('Self-test completed'),
        'ok'
      );

      // Verify polling stopped: advance another 6000ms, no more calls
      await vi.advanceTimersByTimeAsync(6000);
      expect(api.request).toHaveBeenCalledTimes(2);
    });
  });

  describe('copySmartReport', () => {
    it('copies formatted report to clipboard and provides visual checkmark feedback', async () => {
      let clipboardText = '';
      // The clipboard API exists only on secure pages (HTTPS or localhost)
      Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
      Object.assign(navigator, {
        clipboard: {
          writeText: vi.fn(async (text) => {
            clipboardText = text;
          })
        }
      });

      // Populate dummy disk detail response
      vi.spyOn(api, 'request').mockResolvedValue({
        ok: true,
        json: async () => ({
          dev: 'sdb',
          model: 'ST22000NM001E',
          serial: 'ZR500123',
          health: 'PASSED',
          power_on_hours: 2240,
          self_test_progress: { in_progress: false },
          self_test_log: []
        })
      });

      // Poll once to set _currentSmartData
      startSmartPolling('sdb', 'short');
      await vi.advanceTimersByTimeAsync(3000);

      // Invoke copy
      await copySmartReport();

      expect(navigator.clipboard.writeText).toHaveBeenCalled();
      expect(clipboardText).toContain('S.M.A.R.T. Diagnostic Report: /dev/sdb');
      expect(clipboardText).toContain('ST22000NM001E');

      const icon = document.getElementById('smart-copy-report-icon');
      const label = document.getElementById('smart-copy-report-label');
      expect(icon.textContent).toBe('✓');
      expect(label.textContent).toBe('SMART Report Copied!');

      // After 2000ms, reverts back
      await vi.advanceTimersByTimeAsync(2000);
      expect(icon.textContent).toBe('📋');
      expect(label.textContent).toBe('Copy Report');
    });
  });

  describe('switchSmartTab', () => {
    it('activates target tab button and shows corresponding pane while deactivating others', () => {
      switchSmartTab('selftest');

      const tabs = document.querySelectorAll('.smart-tab-btn');
      const healthTab = Array.from(tabs).find((t) => t.dataset.tab === 'health');
      const selftestTab = Array.from(tabs).find((t) => t.dataset.tab === 'selftest');
      const rawTab = Array.from(tabs).find((t) => t.dataset.tab === 'raw');

      expect(selftestTab.classList.contains('active')).toBe(true);
      expect(healthTab.classList.contains('active')).toBe(false);
      expect(rawTab.classList.contains('active')).toBe(false);

      const healthPane = document.getElementById('smart-pane-health');
      const selftestPane = document.getElementById('smart-pane-selftest');
      const rawPane = document.getElementById('smart-pane-raw');

      expect(selftestPane.classList.contains('active')).toBe(true);
      expect(healthPane.classList.contains('active')).toBe(false);
      expect(rawPane.classList.contains('active')).toBe(false);

      // Switch to raw
      switchSmartTab('raw');
      expect(rawPane.classList.contains('active')).toBe(true);
      expect(selftestPane.classList.contains('active')).toBe(false);
    });
  });

  describe('renderSmartLatestReport', () => {
    it('displays the Executive Diagnostic Report Card when latest_report is provided', () => {
      const mockData = {
        dev: 'nvme1n1',
        model: 'WD_BLACK SN7100 2TB',
        power_on_hours: 1420,
        temp: 39,
        latest_report: {
          test_type: 'short',
          passed: true,
          status: 'Completed without error',
          power_on_hours: 1420,
          temp_end: 39,
          lba_first_error: '-',
          recommendation: 'Drive passed all internal self-tests.',
          ts: 1791398000
        }
      };

      renderSmartLatestReport(mockData);

      const card = document.getElementById('smart-latest-report-card');
      const badge = document.getElementById('smart-report-badge');
      const meta = document.getElementById('smart-report-meta');
      const lbaEl = document.getElementById('smart-report-lba');
      const tempEl = document.getElementById('smart-report-temp');
      const hoursEl = document.getElementById('smart-report-hours');
      const typeEl = document.getElementById('smart-report-type');
      const recEl = document.getElementById('smart-report-recommendation');
      const emptyHero = document.getElementById('smart-empty-hero');

      expect(card.style.display).toBe('flex');
      expect(emptyHero.style.display).toBe('none');
      expect(badge.textContent).toContain('Passed');
      expect(meta.textContent).toContain('SHORT');
      expect(meta.textContent).toContain('Completed without error');
      expect(lbaEl.textContent).toContain('0 Defects Detected');
      expect(tempEl.textContent).toBe('39°C');
      expect(hoursEl.textContent).toBe('1,420 h');
      expect(typeEl.textContent).toBe('Short');
      expect(recEl.textContent).toContain('Drive passed all internal self-tests.');
    });

    it('displays failure verdict and defect readout when self-test detects an uncorrectable LBA error', () => {
      const mockData = {
        dev: 'sda',
        model: 'Seagate Exos X20',
        power_on_hours: 8900,
        temp: 42,
        latest_report: {
          test_type: 'extended',
          passed: false,
          status: 'Completed: read failure',
          power_on_hours: 8900,
          temp_end: 43,
          lba_first_error: '12498744',
          recommendation: 'Critical uncorrectable sector found at LBA 12498744. Replace drive immediately.'
        }
      };

      renderSmartLatestReport(mockData);

      const badge = document.getElementById('smart-report-badge');
      const lbaEl = document.getElementById('smart-report-lba');
      const recEl = document.getElementById('smart-report-recommendation');

      expect(badge.textContent).toContain('Failed');
      expect(badge.classList.contains('smart-report-badge-crit')).toBe(true);
      expect(lbaEl.textContent).toBe('Error at LBA 12498744');
      expect(recEl.textContent).toContain('Replace drive immediately.');
    });

    it('shows empty hero CTA when no self-test reports or logs exist on the drive', () => {
      const mockData = {
        dev: 'nvme0n1',
        model: 'Samsung 990 PRO 1TB',
        power_on_hours: 320,
        latest_report: null,
        self_test_log: []
      };

      renderSmartLatestReport(mockData);

      const card = document.getElementById('smart-latest-report-card');
      const emptyHero = document.getElementById('smart-empty-hero');

      expect(card.style.display).toBe('none');
      expect(emptyHero.style.display).toBe('flex');
    });
  });

  describe('generateSmartReportMarkdown with rich latest_report', () => {
    it('uses latest_report.report_markdown when present', () => {
      const mockData = {
        dev: 'nvme1n1',
        latest_report: {
          report_markdown: '# S.M.A.R.T. Diagnostic Report: /dev/nvme1n1\n\n**Verdict**: PASSED\n\nExecutive Diagnostic Summary.'
        }
      };

      const md = generateSmartReportMarkdown(mockData);
      expect(md).toBe('# S.M.A.R.T. Diagnostic Report: /dev/nvme1n1\n\n**Verdict**: PASSED\n\nExecutive Diagnostic Summary.');
    });
  });
});
