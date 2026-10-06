/**
 * ZettNAS Toolkit Hardware Events Logger
 * Renders system alerts, diagnostic events, and handles event log clearing.
 */
import { api } from '../api.js';
import { showToast, showConfirmToast } from '../toast.js';
import { escapeHtml } from '../utils.js';

let _lastEventHash = '';
let _expandedEvents = new Set();
let _currentFilter = 'all';

export function renderEventLog(events) {
  const list = document.getElementById('events-list');
  if (!list) return;

  const currentHash = events ? `${events.length}-${events[0] ? events[0].ts : 0}-${_currentFilter}` : 'empty';
  if (_lastEventHash === currentHash) return;
  _lastEventHash = currentHash;

  if (!events || events.length === 0) {
    list.innerHTML = `<div style="padding: 14px; text-align: center; color: var(--muted); font-size: 11px;">No events logged yet.</div>`;
    return;
  }

  const filtered = _currentFilter === 'all'
    ? events
    : events.filter((e) => e.level === _currentFilter);

  if (filtered.length === 0) {
    list.innerHTML = `<div style="padding: 14px; text-align: center; color: var(--muted); font-size: 11px;">No ${_currentFilter} events.</div>`;
    return;
  }

  list.innerHTML = '';

  filtered.forEach((e) => {
    const dt = new Date(e.ts * 1000);
    const timeStr = dt.toLocaleString();
    let color = '#e2e8f0';
    let icon = 'ℹ️';
    if (e.level === 'error') { color = 'var(--crit)'; icon = '❌'; }
    else if (e.level === 'warning') { color = 'var(--warn)'; icon = '⚠️'; }
    else if (e.level === 'success') { color = 'var(--ok2)'; icon = '✅'; }

    const row = document.createElement('div');
    row.style.cssText = 'padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; gap: 8px; cursor: pointer;';

    row.onmouseover = () => { row.style.background = 'rgba(255,255,255,0.02)'; };
    row.onmouseout = () => { row.style.background = 'transparent'; };

    const topHtml = `
      <div style="display: flex; gap: 10px; align-items: flex-start;">
        <span style="font-size: 14px; margin-top: 2px;">${icon}</span>
        <div style="display: flex; flex-direction: column; gap: 4px; flex-grow: 1;">
          <div style="font-size: 11px; color: ${color}; font-weight: 700; letter-spacing: 0.3px;">${escapeHtml(e.title)}</div>
          <div style="font-size: 12px; color: #fff;">${escapeHtml(e.message)}</div>
          <div style="font-size: 10px; color: var(--muted);">${escapeHtml(timeStr)}</div>
        </div>
        <span style="font-size: 10px; color: var(--muted); padding-top: 4px;">▼ Details</span>
      </div>
    `;

    row.innerHTML = topHtml;

    const detailsBox = document.createElement('pre');
    detailsBox.style.cssText = 'display: none; margin: 0; padding: 10px; background: rgba(0,0,0,0.4); border-radius: 6px; font-size: 10px; color: #a0aec0; border: 1px solid rgba(255,255,255,0.05); white-space: pre-wrap; word-break: break-all;';
    detailsBox.textContent = JSON.stringify(e, null, 2);
    row.appendChild(detailsBox);

    const evKey = `${e.ts}_${e.title}`;
    if (_expandedEvents.has(evKey)) {
      detailsBox.style.display = 'block';
    }

    row.addEventListener('click', () => {
      const isHidden = detailsBox.style.display === 'none';
      detailsBox.style.display = isHidden ? 'block' : 'none';
      if (isHidden) {
        _expandedEvents.add(evKey);
      } else {
        _expandedEvents.delete(evKey);
      }
    });

    list.appendChild(row);
  });
}

export function initEvents() {
  const clearBtn = document.querySelector('.btn-pill-toggle[title="Clear Logs"]') || document.getElementById('btn-clear-events');
  if (clearBtn) {
    clearBtn.addEventListener('click', (e) => {
      e.preventDefault();
      showConfirmToast('Clear Event Log', 'Are you sure you want to clear all logged events?', async () => {
        try {
          await api.delete('/api/events/clear');
          _lastEventHash = '';
          renderEventLog([]);
          showToast('Event log cleared', 'success');
        } catch (err) {
          showToast('Failed to clear events: ' + err.message, 'error');
        }
      });
    });
  }
}
