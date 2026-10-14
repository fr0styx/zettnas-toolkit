import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  renderSelfTestLog,
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
        <div id="smart-actions-container">
          <button id="smart-btn-short-test">Short Test</button>
          <button id="smart-btn-extended-test">Extended Test</button>
          <button id="smart-btn-abort-test" style="display: none;">Abort Test</button>
          <span id="smart-test-status"></span>
        </div>

        <div id="smart-progress-card" class="smart-progress-card" style="display: none;">
          <span class="smart-progress-pulse-dot" id="smart-progress-pulse"></span>
          <span id="smart-progress-status-desc" class="smart-progress-status-desc"></span>
          <span id="smart-progress-pct-label" class="smart-progress-pct-label">0%</span>
          <span id="smart-progress-eta" class="smart-progress-eta" style="display: none;"></span>
          <div class="smart-progress-track">
            <div id="smart-progress-bar" class="smart-progress-bar" style="width: 0%;"></div>
          </div>
        </div>

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

        <pre id="smart-raw-output"></pre>
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
});
