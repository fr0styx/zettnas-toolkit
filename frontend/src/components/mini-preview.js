/**
 * ZettNAS Toolkit Dashboard Layout & Mini-Preview Canvas
 * Handles dynamic modular tile reordering, visibility toggling, scaling, and presets.
 */
import { api } from '../api.js';
import { state, defaultVis, defaultSizes } from '../state.js';
import { showToast } from '../toast.js';

const $ = (id) => document.getElementById(id);
let isDraggingPreview = false;

export function applyDashboardLayout() {
  const screenCanvasEl = $('screen');
  const dashCardsContainer = $('dashboard-cards-container');
  const diskRowEl = $('diskRow');
  if (!dashCardsContainer || !screenCanvasEl) return;

  const cardMap = {};
  dashCardsContainer.querySelectorAll('.card').forEach((c) => {
    cardMap[c.dataset.metricId] = c;
  });

  state.dashOrder.forEach((id) => {
    if (cardMap[id]) dashCardsContainer.appendChild(cardMap[id]);
  });

  const parentContainer = dashCardsContainer.parentElement || screenCanvasEl;
  if (diskRowEl && parentContainer) {
    const disksIdx = state.dashOrder.indexOf('metric-disks');
    const firstCardIdx = state.dashOrder.findIndex((id) => id !== 'metric-disks' && cardMap[id]);
    if (disksIdx !== -1 && firstCardIdx !== -1 && disksIdx < firstCardIdx) {
      parentContainer.insertBefore(diskRowEl, dashCardsContainer);
    } else {
      parentContainer.appendChild(diskRowEl);
    }
  }

  let allTopHidden = true;
  Object.keys(state.dashVis).forEach((id) => {
    if (id !== 'metric-disks' && cardMap[id]) {
      const isHidden = !state.dashVis[id];
      cardMap[id].classList.toggle('card-hidden', isHidden);
      if (!isHidden) allTopHidden = false;
      cardMap[id].classList.toggle('card-compact', state.dashSizes[id] === 'compact');
    }
  });

  dashCardsContainer.classList.toggle('card-hidden', allTopHidden);

  if (diskRowEl) {
    diskRowEl.classList.toggle('card-hidden', state.dashVis['metric-disks'] === false);
    diskRowEl.classList.toggle('compact', state.dashSizes['metric-disks'] === 'compact');
  }

  screenCanvasEl.classList.toggle('no-disks', state.dashVis['metric-disks'] === false);
  screenCanvasEl.classList.toggle('no-cards', allTopHidden);

  document.querySelectorAll('.dash-module-item').forEach((item) => {
    const id = item.dataset.metricTarget;
    const isEnabled = state.dashVis[id] !== false;
    item.classList.toggle('disabled', !isEnabled);

    const toggle = item.querySelector('.metric-vis-toggle');
    if (toggle) toggle.checked = isEnabled;

    const currentSize = state.dashSizes[id] || 'full';
    item.querySelectorAll('.seg-size-btn').forEach((sBtn) => {
      sBtn.classList.toggle('active', sBtn.dataset.size === currentSize);
    });
  });

  if ($('clock-format-btn')) {
    $('clock-format-btn').textContent = state.clockFormat === '12' ? '12 Hours' : '24 Hours';
  }

  evaluateActivePreset();
  syncMiniPreviewStructure();
}

export function evaluateActivePreset() {
  const presetBadge = $('preset-state-badge');
  const isVisMatch = (v) => Object.keys(v).every((k) => state.dashVis[k] === v[k]);

  const isDefault = isVisMatch(defaultVis);
  const isThermal = isVisMatch({ 'metric-storage': false, 'metric-cpu': true, 'metric-mem': false, 'metric-fans': true, 'metric-net': false, 'metric-disks': true });
  const isStorage = isVisMatch({ 'metric-storage': true, 'metric-cpu': false, 'metric-mem': false, 'metric-fans': false, 'metric-net': false, 'metric-disks': true });

  let activeKey = null;
  if (isDefault) activeKey = 'default';
  else if (isThermal) activeKey = 'thermal';
  else if (isStorage) activeKey = 'storage';

  document.querySelectorAll('.preset-btn-card').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.preset === activeKey);
  });

  if (presetBadge) {
    presetBadge.textContent = activeKey ? activeKey.toUpperCase() : 'CUSTOM';
  }
}

export async function persistDashboardLayout() {
  try {
    const resp = await api.post('/api/layout', {
      order: state.dashOrder,
      vis: state.dashVis,
      sizes: state.dashSizes,
      clock_format: state.clockFormat,
      timezone: state.currentTimezone
    });
    if (resp.layout && resp.layout.version) {
      state.activeLayoutVersion = resp.layout.version;
    }
  } catch (err) {
    console.warn('Could not persist layout', err);
  }
}

export async function fetchDashboardLayout() {
  try {
    const data = await api.get('/api/layout');
    if (data.version) state.activeLayoutVersion = data.version;
    if (data.order) state.dashOrder = data.order;
    if (data.vis) state.dashVis = data.vis;
    if (data.sizes) state.dashSizes = data.sizes;
    if (data.clock_format) state.clockFormat = data.clock_format;
    if (data.timezone) state.currentTimezone = data.timezone;
  } catch (err) {
    console.warn('Failed to load layout from server:', err);
  }
  applyDashboardLayout();
}

export function syncMiniPreviewStructure() {
  const miniInner = $('mini-preview-inner');
  const screenEl = $('screen');
  if (!miniInner || !screenEl) return;

  let miniCardsContainer = miniInner.querySelector('.cards');
  let miniDiskRow = miniInner.querySelector('.disks');
  const screenDiskRow = screenEl.querySelector('#diskRow');

  if (!miniCardsContainer || !miniDiskRow) {
    miniInner.innerHTML = screenEl.innerHTML.replace(/\s+id="[^"]*"/g, '');
    miniCardsContainer = miniInner.querySelector('.cards');
    miniDiskRow = miniInner.querySelector('.disks');
    miniInner.className = 'mini-preview-inner ' + screenEl.className;
    setupMiniPreviewInteractivity();
  }

  if (screenDiskRow && screenDiskRow.children.length > 0 && miniDiskRow.children.length === 0) {
    miniDiskRow.innerHTML = screenDiskRow.innerHTML.replace(/\s+id="[^"]*"/g, '');
  }

  const sFanRowStruct = screenEl.querySelector('.fan-row');
  const dFanRowStruct = miniInner.querySelector('.fan-row');
  if (sFanRowStruct && dFanRowStruct) {
    dFanRowStruct.innerHTML = sFanRowStruct.innerHTML;
    dFanRowStruct.className = sFanRowStruct.className;
  }

  const cardMap = {};
  miniCardsContainer.querySelectorAll('.card').forEach((c) => {
    cardMap[c.dataset.metricId] = c;
  });

  state.dashOrder.forEach((id) => {
    if (cardMap[id]) miniCardsContainer.appendChild(cardMap[id]);
  });

  const miniParent = (miniCardsContainer && miniCardsContainer.parentElement) || miniInner;
  const disksIdx = state.dashOrder.indexOf('metric-disks');
  const firstCardIdx = state.dashOrder.findIndex((id) => id !== 'metric-disks' && cardMap[id]);
  if (miniDiskRow && miniParent) {
    if (disksIdx !== -1 && firstCardIdx !== -1 && disksIdx < firstCardIdx) {
      miniParent.insertBefore(miniDiskRow, miniCardsContainer);
    } else {
      miniParent.appendChild(miniDiskRow);
    }
  }

  Object.keys(state.dashVis).forEach((id) => {
    if (id !== 'metric-disks' && cardMap[id]) {
      cardMap[id].classList.toggle('card-hidden', !state.dashVis[id]);
      cardMap[id].classList.toggle('card-compact', state.dashSizes[id] === 'compact');
    }
  });

  miniDiskRow.classList.toggle('card-hidden', state.dashVis['metric-disks'] === false);
  miniDiskRow.classList.toggle('compact', state.dashSizes['metric-disks'] === 'compact');

  const sHeader = screenEl.querySelector('header');
  const mHeader = miniInner.querySelector('header');
  const stripIds = (html) => html.replace(/\s+id="[^"]*"/g, '');
  if (sHeader && mHeader) mHeader.innerHTML = stripIds(sHeader.innerHTML);

  Object.keys(cardMap).forEach((id) => {
    const sCard = screenEl.querySelector(`[data-metric-id="${id}"]`);
    if (sCard && cardMap[id]) {
      cardMap[id].innerHTML = stripIds(sCard.innerHTML);
    }
  });

  miniInner.className = 'mini-preview-inner ' + screenEl.className;
  fitMiniPreviewScale();
}

export function fitMiniPreviewScale() {
  if (window.innerWidth <= 720) {
    const inner = $('mini-preview-inner');
    if (inner) inner.style.transform = '';
    return;
  }
  const canvas = $('mini-lcd-canvas');
  const inner = $('mini-preview-inner');
  if (!canvas || !inner) return;
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;
  if (!cw || !ch) return;
  const sW = (cw - 4) / 640;
  const sH = (ch - 4) / 172;
  const s = Math.min(sW, sH, 0.78);
  inner.style.setProperty('--mini-scale', s.toFixed(3));
  inner.style.transform = `translate(-50%, -50%) scale(${s.toFixed(3)})`;
}

export function syncMiniPreviewTelemetry() {
  const miniInner = document.getElementById('mini-preview-inner');
  const screenEl = document.getElementById('screen');
  if (!miniInner || !screenEl || isDraggingPreview) return;

  const stripIds = (html) => html.replace(/\s+id="[^"]*"/g, '');

  const sHeader = screenEl.querySelector('header');
  const mHeader = miniInner.querySelector('header');
  if (sHeader && mHeader) mHeader.innerHTML = stripIds(sHeader.innerHTML);

  const miniCardsContainer = miniInner.querySelector('.cards');
  if (miniCardsContainer) {
    miniCardsContainer.querySelectorAll('.card').forEach((c) => {
      const id = c.dataset.metricId;
      if (id) {
        const sCard = screenEl.querySelector(`[data-metric-id="${id}"]`);
        if (sCard) c.innerHTML = stripIds(sCard.innerHTML);
      }
    });
  }

  const screenDiskRow = screenEl.querySelector('#diskRow');
  const miniDiskRow = miniInner.querySelector('.disks');
  if (screenDiskRow && miniDiskRow) {
    miniDiskRow.innerHTML = stripIds(screenDiskRow.innerHTML);
  }
}

export function setupMiniPreviewInteractivity() {
  const miniInner = $('mini-preview-inner');
  if (!miniInner) return;

  let draggedMetricId = null;

  miniInner.querySelectorAll('.card, .disks').forEach((el) => {
    const metricId = el.dataset.metricId;
    if (!metricId) return;

    el.setAttribute('draggable', 'true');

    el.addEventListener('dragstart', (e) => {
      e.stopPropagation();
      isDraggingPreview = true;
      draggedMetricId = metricId;
      el.classList.add('mini-dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', metricId);
    });

    el.addEventListener('dragend', (e) => {
      e.stopPropagation();
      isDraggingPreview = false;
      draggedMetricId = null;
      el.classList.remove('mini-dragging');
      miniInner.querySelectorAll('.card, .disks').forEach((c) => c.classList.remove('mini-drag-over'));
    });

    el.addEventListener('dragover', (e) => {
      if (!draggedMetricId || draggedMetricId === metricId) return;
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = 'move';
      el.classList.add('mini-drag-over');
    });

    el.addEventListener('dragleave', (e) => {
      e.stopPropagation();
      el.classList.remove('mini-drag-over');
    });

    el.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      el.classList.remove('mini-drag-over');
      if (!draggedMetricId) return;

      const cardsEl = miniInner.querySelector('.cards');
      const refRect = cardsEl ? cardsEl.getBoundingClientRect() : miniInner.getBoundingClientRect();
      const isLowerHalf = e.clientY > (refRect.top + refRect.height / 2);

      if (draggedMetricId === 'metric-disks') {
        // Just swap the position of disks!
        const wasFirst = state.dashOrder.indexOf('metric-disks') === 0;
        const newOrder = state.dashOrder.filter((x) => x !== 'metric-disks');
        if (wasFirst) newOrder.push('metric-disks');
        else newOrder.unshift('metric-disks');
        state.dashOrder = newOrder;
      } else if (metricId === 'metric-disks') {
        // Dragging a card onto the disks deck -> swap the decks too!
        const wasFirst = state.dashOrder.indexOf('metric-disks') === 0;
        const newOrder = state.dashOrder.filter((x) => x !== 'metric-disks');
        if (wasFirst) newOrder.push('metric-disks');
        else newOrder.unshift('metric-disks');
        state.dashOrder = newOrder;
      } else {
        const oldIdx = state.dashOrder.indexOf(draggedMetricId);
        const targetIdx = state.dashOrder.indexOf(metricId);
        if (oldIdx !== -1 && targetIdx !== -1 && oldIdx !== targetIdx) {
          const newOrder = [...state.dashOrder];
          newOrder.splice(oldIdx, 1);
          newOrder.splice(targetIdx, 0, draggedMetricId);
          state.dashOrder = newOrder;
        }
      }

      isDraggingPreview = false;
      draggedMetricId = null;

      try {
        applyDashboardLayout();
      } catch (err) {
        console.error('applyDashboardLayout failed:', err);
      }
      persistDashboardLayout();
    });
  });

  const miniCardsContainer = miniInner.querySelector('.cards');
  if (miniCardsContainer) {
    miniCardsContainer.addEventListener('dragover', (e) => {
      if (!draggedMetricId) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    });

    miniCardsContainer.addEventListener('drop', (e) => {
      if (!draggedMetricId) return;
      if (draggedMetricId === 'metric-disks') {
        e.preventDefault();
        e.stopPropagation();
        // Just swap the position of disks! If it was first, put it last. If it was last, put it first.
        const wasFirst = state.dashOrder.indexOf('metric-disks') === 0;
        const newOrder = state.dashOrder.filter((x) => x !== 'metric-disks');
        if (wasFirst) newOrder.push('metric-disks'); // move to bottom
        else newOrder.unshift('metric-disks'); // move to top
        state.dashOrder = newOrder;
        
        isDraggingPreview = false;
        draggedMetricId = null;
        try {
          applyDashboardLayout();
        } catch (err) {
          console.error('applyDashboardLayout failed:', err);
        }
        persistDashboardLayout();
        return;
      }
      
      if (e.target === miniCardsContainer) {
        e.preventDefault();
        const dropX = e.clientX;
        const cards = Array.from(miniCardsContainer.querySelectorAll('.card'));
        let closestCardId = null;
        let minDiff = Infinity;
        cards.forEach((c) => {
          const cr = c.getBoundingClientRect();
          const cardCenter = cr.left + cr.width / 2;
          const diff = Math.abs(dropX - cardCenter);
          if (diff < minDiff) {
            minDiff = diff;
            closestCardId = c.dataset.metricId;
          }
        });
        if (closestCardId && closestCardId !== draggedMetricId) {
          const oldIdx = state.dashOrder.indexOf(draggedMetricId);
          const targetIdx = state.dashOrder.indexOf(closestCardId);
          if (oldIdx !== -1 && targetIdx !== -1 && oldIdx !== targetIdx) {
            const newOrder = [...state.dashOrder];
            newOrder.splice(oldIdx, 1);
            newOrder.splice(targetIdx, 0, draggedMetricId);
            state.dashOrder = newOrder;
            try {
              applyDashboardLayout();
            } catch (err) {
              console.error('applyDashboardLayout failed:', err);
            }
            persistDashboardLayout();
          }
        }
        isDraggingPreview = false;
        draggedMetricId = null;
      }
    });
  }

  miniInner.addEventListener('dragover', (e) => {
    if (!draggedMetricId) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  });

  miniInner.addEventListener('drop', (e) => {
    if (!draggedMetricId) return;
    const cardsEl = miniInner.querySelector('.cards');
    const refRect = cardsEl ? cardsEl.getBoundingClientRect() : miniInner.getBoundingClientRect();
    const isLowerHalf = e.clientY > (refRect.top + refRect.height / 2);

    if (draggedMetricId === 'metric-disks') {
      const wasFirst = state.dashOrder.indexOf('metric-disks') === 0;
      const newOrder = state.dashOrder.filter((x) => x !== 'metric-disks');
      if (wasFirst) newOrder.push('metric-disks');
      else newOrder.unshift('metric-disks');
      state.dashOrder = newOrder;
      isDraggingPreview = false;
      draggedMetricId = null;
      try {
        applyDashboardLayout();
      } catch (err) {
        console.error('applyDashboardLayout failed:', err);
      }
      persistDashboardLayout();
    }
  });
}
