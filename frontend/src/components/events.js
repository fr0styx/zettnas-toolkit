/**
 * Kiboto Hardware Events Logger
 * Renders system alerts, diagnostic events, and handles event log clearing.
 */
import { eventView, eventWhen } from '../event-view.js';
import { escapeHtml } from '../utils.js';

import { t, getLanguage } from '../i18n.js';
import { formatDateTime } from '../format.js';
import { emptyStateHtml } from './empty-state.js';
import { state } from '../state.js';
let _lastEventHash = '';
let _expandedEvents = new Set();
let _currentFilter = 'all';

export function renderEventLog(events) {
  const list = document.getElementById('events-list');
  if (!list) return;

  // a counted repeat changes neither the length nor the first time: the hash carries both, and the language
  const top = events && events[0];
  const currentHash = events ? `${events.length}-${top ? `${top.id}-${eventWhen(top)}-${top.count || 1}` : 0}-${_currentFilter}-${getLanguage()}` : 'empty';
  if (_lastEventHash === currentHash) return;
  _lastEventHash = currentHash;

  if (!events || events.length === 0) {
    list.innerHTML = emptyStateHtml({
      compact: true,
      title: t('events.none_title', 'Nothing has happened yet'),
      body: t('events.none_desc', 'Alerts, backups, power, app and hardware events appear here as they happen.'),
    });
    return;
  }

  const filtered = _currentFilter === 'all'
    ? events
    : events.filter((e) => e.level === _currentFilter);

  if (filtered.length === 0) {
    list.innerHTML = `<div style="padding: 14px; text-align: center; color: var(--muted); font-size: var(--zn-fs-xs);">${escapeHtml(t('evx.none', 'No {level} events.', { level: _currentFilter }))}</div>`;
    return;
  }

  list.innerHTML = '';

  filtered.forEach((e) => {
    const text = eventView(e); // one view for the log, the bell and the dialog (SET-13)
    const { color, icon } = text;
    const timeStr = [formatDateTime(new Date(text.when * 1000)), text.repeated].filter(Boolean).join(' · ');

    const row = document.createElement('div');
    row.style.cssText = 'padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; gap: 8px; cursor: pointer;';

    row.onmouseover = () => { row.style.background = 'rgba(255,255,255,0.02)'; };
    row.onmouseout = () => { row.style.background = 'transparent'; };

    const topHtml = `
      <div style="display: flex; gap: 10px; align-items: flex-start;">
        <span style="font-size: 14px; margin-top: 2px;">${icon}</span>
        <div style="display: flex; flex-direction: column; gap: 4px; flex-grow: 1;">
          <div style="font-size: var(--zn-fs-xs); color: ${color}; font-weight: 700; letter-spacing: 0.3px;">${escapeHtml(text.title)}</div>
          <div style="font-size: var(--zn-fs-xs); color: var(--zn-text-strong);">${escapeHtml(text.message)}</div>
          <div style="font-size: var(--zn-fs-xs); color: var(--muted);">${escapeHtml(timeStr)}</div>
        </div>
        <div style="display: flex; gap: 6px; align-items: center; padding-top: 2px;">
          <button class="event-inspect-btn" type="button" title="${t('ui.view_full_event_details', 'View full event details')}" style="background: rgba(51, 205, 184, 0.15); border: 1px solid rgba(51, 205, 184, 0.35); color: var(--zn-text-accent); font-size: var(--zn-fs-xs); font-weight: 700; padding: 2px 7px; border-radius: 4px; cursor: pointer; display: inline-flex; align-items: center; gap: 3px;">
            <span aria-hidden="true">🔍</span> <span>${t('evx.more', 'More Info')}</span>
          </button>
          <span style="font-size: var(--zn-fs-xs); color: var(--muted); cursor: pointer; padding: 2px 4px;"><span aria-hidden="true">▼</span> ${t('evx.details', 'Details')}</span>
        </div>
      </div>
    `;

    row.innerHTML = topHtml;

    const detailsBox = document.createElement('pre');
    detailsBox.style.cssText = 'display: none; margin: 0; padding: 10px; background: rgba(0,0,0,0.4); border-radius: 6px; font-size: var(--zn-fs-xs); color: #a4b8bc; border: 1px solid rgba(255,255,255,0.05); white-space: pre-wrap; word-break: break-all;';
    detailsBox.textContent = JSON.stringify(e, null, 2);
    row.appendChild(detailsBox);

    const evKey = `${e.ts}_${e.title}`;
    if (_expandedEvents.has(evKey)) {
      detailsBox.style.display = 'block';
    }

    const inspectBtn = row.querySelector('.event-inspect-btn');
    if (inspectBtn) {
      inspectBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        if (window.openEventDetailModal) {
          window.openEventDetailModal(e);
        }
      });
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
  // The stats stream sends the events only when they change, usually before this list existed:
  // draw the ones the page already has
  _lastEventHash = '';
  if (state.latestStats?.events) renderEventLog(state.latestStats.events);
  // "Clear Event Log" is gone (SET-13): it deleted for everyone, with no undo and no record of
  // who did it. Entries leave by themselves after 90 days.
  window.addEventListener('kiboto:lang-changed', () => {
    if (state.latestStats?.events) renderEventLog(state.latestStats.events); // the open log kept the old language
  });
}
