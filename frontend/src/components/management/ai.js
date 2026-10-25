/**
 * Mission Control: AI search, models, knowledge folders, chat and conversations.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { openStackModal } from '../stack-modal.js';
import { ZettEventBus } from '../../event-bus.js';
import { api, auth } from '../../api.js';
import { showToast, showConfirmToast, showPromptToast } from '../../toast.js';
import { escapeHtml, copyText } from '../../utils.js';
import { t } from '../../i18n.js';
import { immichResultsHtml } from '../immich-settings.js';
import { formatDateTime, formatNumber, formatTime } from '../../format.js';

// ============================================================================
// ZettAI — Multi-Modal Local RAG & Visual Search Engine Controller
// ============================================================================
/** The sentences of an answer that the sources do not back up (AI-1), for a closer look. */
export function unsupportedHtml(detail) {
  const rows = (detail && Array.isArray(detail.sentences) ? detail.sentences : []).filter((r) => !r.supported);
  if (!rows.length) return '';
  return `<details class="ai-unsupported"><summary>${escapeHtml(t('ai.unsupported_title', 'Not found in the sources'))} (${rows.length})</summary><ul>${rows
    .map((r) => `<li>${escapeHtml(r.text)}</li>`)
    .join('')}</ul></details>`;
}

export let _aiSelectedColor = '';
export let _aiSelectedScene = '';
let _aiSelectedFileType = 'all';
let _aiSelectedMatchTab = 'semantic';
let _aiSelectedSortBy = 'relevance';
let _aiWatchedPaths = ['/mnt/user'];
let _aiAvailableFolders = [];
let _aiSyncPollTimer = null;
let _aiLastResultsList = [];
let _aiSearchHistory = [];
try {
  const savedHist = JSON.parse(localStorage.getItem('zettnas_ai_search_history') || '[]');
  if (Array.isArray(savedHist)) _aiSearchHistory = savedHist.slice(0, 8);
} catch (_) {}

function _recordAiSearchHistory(query) {
  const clean = String(query || '').trim();
  if (!clean) return;
  _aiSearchHistory = [clean, ..._aiSearchHistory.filter((q) => q.toLowerCase() !== clean.toLowerCase())].slice(0, 8);
  try {
    localStorage.setItem('zettnas_ai_search_history', JSON.stringify(_aiSearchHistory));
  } catch (_) {}
  renderAiSearchHistory();
}

export function renderAiSearchHistory() {
  const bar = document.getElementById('ai-history-bar');
  const chipsContainer = document.getElementById('ai-history-chips');
  if (!bar || !chipsContainer) return;
  if (!_aiSearchHistory.length) {
    bar.style.display = 'none';
    chipsContainer.innerHTML = '';
    return;
  }
  bar.style.display = 'flex';
  chipsContainer.innerHTML = _aiSearchHistory.map((q) => `
    <button type="button" class="btn-pill-toggle ai-history-chip is-small" data-query="${escapeHtml(q)}" style="background: var(--lt-b-ffffff0a, rgba(255,255,255,0.04)); border: 1px solid var(--lt-r-ffffff1f, rgba(255,255,255,0.12)); color: var(--lt-t-cbd5e1ff, #cbd5e1);">
      ${escapeHtml(q)}
    </button>
  `).join('');
  chipsContainer.querySelectorAll('.ai-history-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      const q = chip.dataset.query || '';
      const askInput = document.getElementById('ai-rag-query-input');
      if (askInput) askInput.value = q;
      const visInput = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
      if (visInput) visInput.value = q;
      runAiRagAsk(q, { unifiedMode: true });
      runAiVisualSearch(q);
    });
  });
}

function _ensureAiSyncPoll(shouldPoll) {
  if (shouldPoll) {
    if (!_aiSyncPollTimer) {
      _aiSyncPollTimer = setInterval(() => {
        fetchAndRenderAiStatus().catch(() => {});
      }, 1500);
    }
  } else if (_aiSyncPollTimer) {
    clearInterval(_aiSyncPollTimer);
    _aiSyncPollTimer = null;
  }
}

export function setAiVisualFiltersDrawerOpen(forceOpen = null) {
  const drawer = document.getElementById('ai-visual-filters-drawer');
  const toggleBtn = document.getElementById('btn-ai-toggle-visual-filters');
  const caret = document.getElementById('ai-visual-filters-caret');
  if (!drawer) return false;
  const isCurrentlyOpen = drawer.style.display !== 'none';
  const nextOpen = forceOpen !== null ? Boolean(forceOpen) : !isCurrentlyOpen;
  drawer.style.display = nextOpen ? 'flex' : 'none';
  if (toggleBtn) {
    toggleBtn.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
    toggleBtn.style.borderColor = (nextOpen || _aiSelectedColor || _aiSelectedScene)
      ? 'rgba(56,189,248,0.55)'
      : 'rgba(56,189,248,0.3)';
  }
  if (caret) {
    caret.textContent = nextOpen ? '▴' : '▾';
  }
  return nextOpen;
}

function _updateAiVisualFilterBadge() {
  const badge = document.getElementById('ai-visual-filters-active-badge');
  if (!badge) return;
  const activeCount = (_aiSelectedColor ? 1 : 0) + (_aiSelectedScene ? 1 : 0);
  if (activeCount > 0) {
    const parts = [_aiSelectedColor, _aiSelectedScene].filter(Boolean);
    badge.style.display = 'inline-block';
    badge.textContent = parts.join(' + ');
  } else {
    badge.style.display = 'none';
    badge.textContent = '';
  }
}

let _aiLastLlmRecommendations = null;
let _aiLastActiveModel = ''; // the model the server reported; never a made-up default (FE-15)
let _aiActiveHfFilter = 'all';
let _aiModelsSortBy = 'date';
let _aiSortListenerAttached = false;

export function renderAiLlmRecommendations(recData = {}, activeModel = '') {
  if (recData && Array.isArray(recData.models)) {
    _aiLastLlmRecommendations = recData;
  }
  const headlineEl = document.getElementById('ai-llm-advisor-headline');
  const summaryEl = document.getElementById('ai-llm-advisor-summary');
  const gridEl = document.getElementById('ai-llm-recommendations-grid');
  const topSelect = document.getElementById('ai-top-model-select');
  const sortSelect = document.getElementById('ai-models-sort-select');

  if (sortSelect) {
    if (!_aiSortListenerAttached) {
      _aiSortListenerAttached = true;
      sortSelect.addEventListener('change', (e) => {
        _aiModelsSortBy = e.target.value || 'date';
        if (_aiLastLlmRecommendations) {
          renderAiLlmRecommendations(_aiLastLlmRecommendations, _aiLastActiveModel);
        }
      });
    }
    sortSelect.value = _aiModelsSortBy;
  }

  if (headlineEl && recData.headline) {
    headlineEl.textContent = recData.headline;
  }
  if (summaryEl && recData.hardware_summary) {
    summaryEl.textContent = recData.hardware_summary;
  }

  const allModelsRaw = Array.isArray(recData.models) ? recData.models : [];
  const currentActive = activeModel || recData.active_model || _aiLastActiveModel || '';
  _aiLastActiveModel = currentActive;

  // Filter out any models that do not fit the user's hardware from the catalog,
  // AND strictly filter out older models released before 2026 (2024, 2025, etc.)
  const allModels = allModelsRaw.filter((m) => {
    // Release year filter: strictly 2026 or newer
    const relStr = String(m.release_date_str || m.release_date || m.created_at || '').trim();
    const ts = Number(m.release_timestamp || 0);
    if (ts > 0 && ts < 1767225600.0) return false;
    if (/\b(20[0-2][0-5])\b/.test(relStr)) return false;

    const isAct = m.id === currentActive || Boolean(m.active);
    const isHfSearch = m.source === 'huggingface_hub' && !m.pulled_from_hf;
    const hasWarn = m.fits_hardware === false || Boolean(m.hardware_warning) || m.fit_status === 'insufficient_ram' || m.fit_status === 'insufficient_vram';
    return !hasWarn || isAct || isHfSearch;
  });

  // Sort models by chosen sort option (Release Date, Recommended, Downloads, Size)
  allModels.sort((a, b) => {
    if (_aiModelsSortBy === 'date') {
      const tsA = Number(a.release_timestamp || 0);
      const tsB = Number(b.release_timestamp || 0);
      if (tsB !== tsA) return tsB - tsA;
      return Number(b.downloads || 0) - Number(a.downloads || 0);
    }
    if (_aiModelsSortBy === 'recommended') {
      const recA = a.recommended ? 1 : 0;
      const recB = b.recommended ? 1 : 0;
      if (recB !== recA) return recB - recA;
      return Number(b.release_timestamp || 0) - Number(a.release_timestamp || 0);
    }
    if (_aiModelsSortBy === 'downloads') {
      return Number(b.downloads || 0) - Number(a.downloads || 0);
    }
    if (_aiModelsSortBy === 'size_asc') {
      const szA = Number(a.vram_or_ram_gb ?? a.est_ram_gb ?? 0);
      const szB = Number(b.vram_or_ram_gb ?? b.est_ram_gb ?? 0);
      return szA - szB;
    }
    if (_aiModelsSortBy === 'size_desc') {
      const szA = Number(a.vram_or_ram_gb ?? a.est_ram_gb ?? 0);
      const szB = Number(b.vram_or_ram_gb ?? b.est_ram_gb ?? 0);
      return szB - szA;
    }
    return 0;
  });

  const activeLlmLabel = document.getElementById('ai-active-llm-label');
  const activeLlmPill = document.getElementById('ai-active-llm-pill');
  if (activeLlmLabel) {
    activeLlmLabel.textContent = currentActive;
  }
  if (activeLlmPill) {
    activeLlmPill.title = `Active Local LLM: ${currentActive} — Leveraged by RAG Synthesis & NAS Copilot Chatbot`;
  }
  const chatModelBadge = document.getElementById('ai-chat-active-model-badge');
  if (chatModelBadge) {
    const activeObj = allModels.find((m) => m.id === currentActive || m.active);
    const rawDev = activeObj?.target_device ? String(activeObj.target_device) : 'NPU Tier 1';
    const devLabel = rawDev.replace(/\s*\([^)]*\)?/g, '').split('/')[0].trim() || 'NPU Tier 1';
    chatModelBadge.textContent = `🤖 ${currentActive} (${devLabel})`;
  }

  // Update filter pill counts if present - hide the warning pill since all shown models fit
  const filterBtns = document.querySelectorAll('.ai-hf-filter-btn');
  const warnBtn = document.querySelector('.ai-hf-filter-btn[data-hf-filter="warning"]');
  if (warnBtn) {
    warnBtn.style.display = 'none';
  }
  if (filterBtns.length > 0 && allModels.length > 0) {
    filterBtns.forEach((btn) => {
      const fType = btn.dataset.hfFilter || 'all';
      btn.classList.toggle('active', fType === 'all' || fType === 'compatible');
      if (fType === 'all') {
        btn.textContent = `2026+ Releases (${allModels.length})`;
      } else if (fType === 'compatible') {
        btn.textContent = `✅ Fits Hardware (${allModels.length})`;
      }
    });
  }

  if (topSelect && allModels.length > 0) {
    topSelect.innerHTML = allModels.map((m) => {
      const isAct = m.id === currentActive || Boolean(m.active);
      const prefix = m.recommended ? '★ ' : '✓ ';
      return `<option value="${escapeHtml(m.id)}" ${isAct ? 'selected' : ''}>${prefix}${escapeHtml(m.name)} (${escapeHtml(m.quantization || 'INT4')})</option>`;
    }).join('');
    topSelect.value = currentActive;
  }

  if (!gridEl || allModels.length === 0) return;

  const filteredModels = allModels;

  if (filteredModels.length === 0) {
    gridEl.innerHTML = `<div style="grid-column:1 / -1; padding:14px; text-align:center; color:var(--muted,#94a3b8); font-size:11.5px; border:1px dashed var(--lt-r-ffffff1f, rgba(255,255,255,0.12)); border-radius:8px;">No models match the selected hardware filter.</div>`;
    return;
  }

  gridEl.innerHTML = filteredModels.map((m) => {
    const isAct = m.id === currentActive || Boolean(m.active);
    const isRec = Boolean(m.recommended);
    const hasWarn = m.fits_hardware === false || Boolean(m.hardware_warning) || m.fit_status === 'insufficient_ram' || m.fit_status === 'insufficient_vram';
    const isCritical = m.warning_severity === 'critical' || m.fit_status === 'insufficient_ram';
    const hfRepo = m.hf_repo || m.id || '';
    const hfUrl = m.hf_url || (hfRepo.includes('/') ? `https://huggingface.co/${hfRepo}` : 'https://huggingface.co/models');
    const isLiveHfResult = m.source === 'huggingface_hub' && !m.pulled_from_hf;
    const releaseDateText = m.release_date_str || m.release_date || 'Recent';

    const borderCol = isAct
      ? 'rgba(52,211,153,0.65)'
      : hasWarn
        ? (isCritical ? 'rgba(239,68,68,0.62)' : 'rgba(245,158,11,0.62)')
        : isRec
          ? 'rgba(56,189,248,0.45)'
          : 'rgba(255,255,255,0.09)';
    const bgCol = isAct
      ? 'rgba(16,185,129,0.09)'
      : hasWarn
        ? (isCritical ? 'rgba(239,68,68,0.07)' : 'rgba(245,158,11,0.07)')
        : isRec
          ? 'rgba(14,165,233,0.07)'
          : 'rgba(255,255,255,0.025)';
    const badgeBg = hasWarn
      ? (isCritical ? 'rgba(239,68,68,0.22)' : 'rgba(245,158,11,0.22)')
      : isRec
        ? 'rgba(56,189,248,0.18)'
        : 'rgba(16,185,129,0.15)';
    const badgeColor = hasWarn
      ? (isCritical ? '#fca5a5' : '#fcd34d')
      : isRec
        ? '#38bdf8'
        : '#6ee7b7';
    const warningText = m.warning_message || m.fit_reason || 'Warning: This model exceeds your NAS hardware memory/VRAM capacity.';

    return `
      <div class="ai-llm-rec-card ${hasWarn ? 'ai-llm-hw-warning' : 'ai-llm-hw-ok'}" data-model-id="${escapeHtml(m.id)}" data-hf-repo="${escapeHtml(hfRepo)}" data-recommended="${isRec ? '1' : '0'}" data-active="${isAct ? '1' : '0'}" data-fits-hardware="${hasWarn ? '0' : '1'}" data-hardware-warning="${hasWarn ? '1' : '0'}" style="background:${bgCol}; border:1px solid ${borderCol}; border-radius:9px; padding:10px 12px; display:flex; flex-direction:column; gap:6px;">
        <div style="display:flex; flex-direction:column; gap:4px;">
          <div style="font-weight:800; font-size:12.5px; color:var(--lt-t-ffffffff, #fff); word-break:break-word; line-height:1.35;" title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</div>
          <div style="display:flex; justify-content:space-between; align-items:center; gap:6px; flex-wrap:wrap;">
            <div style="font-size:11px; color:var(--muted,#94a3b8); display:flex; align-items:center; gap:5px; flex-wrap:wrap;">
              <span>${escapeHtml(m.family || m.category || 'Hugging Face')} • ${escapeHtml(m.params || '')} • ${escapeHtml(m.quantization || '')}</span>
              ${hfRepo ? `<a href="${escapeHtml(hfUrl)}" target="_blank" rel="noopener noreferrer" style="color:var(--lt-t-fde047ff, #fde047); text-decoration:none; font-family:monospace; font-size:11px;" title="View on https://huggingface.co">🤗 ${escapeHtml(hfRepo)} ↗</a>` : ''}
            </div>
            <span class="ai-model-fit-badge" style="font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px; background:${badgeBg}; color:${badgeColor}; white-space:nowrap; display:inline-flex; align-items:center; gap:3px;">
              ${escapeHtml(m.fit_badge || (hasWarn ? "⚠️ Doesn't Fit Hardware" : (isRec ? '★ Recommended' : '✓ Fits Hardware')))}
            </span>
          </div>
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:5px; font-size:11px;">
          <span style="padding:1px 6px; border-radius:4px; background:var(--lt-b-0000004c, rgba(0,0,0,0.3)); color:${hasWarn ? '#fca5a5' : '#6ee7b7'};">⚡ ${escapeHtml(m.target_device || 'NPU / GPU')}</span>
          <span style="padding:1px 6px; border-radius:4px; background:var(--lt-b-0000004c, rgba(0,0,0,0.3)); color:${hasWarn ? '#fdba74' : '#bae6fd'};">💾 ~${m.vram_or_ram_gb ?? m.est_ram_gb ?? 2.0} GB Model${m.min_ram_gb ? ` (${m.min_ram_gb}GB+ Host)` : ''}</span>
          <span style="padding:1px 6px; border-radius:4px; background:var(--lt-b-0000004c, rgba(0,0,0,0.3)); color:var(--lt-t-f8fafcff, #f8fafc);" title="Hugging Face Release Date: ${escapeHtml(releaseDateText)}">📅 ${escapeHtml(releaseDateText)}</span>
          <span style="padding:1px 6px; border-radius:4px; background:var(--lt-b-0000004c, rgba(0,0,0,0.3)); color:var(--lt-t-fde68aff, #fde68a);">🚀 ${escapeHtml(m.estimated_speed || '')}</span>
        </div>
        ${hasWarn ? `
          <div class="ai-model-hw-warning-banner" style="padding:6px 8px; border-radius:6px; background:${isCritical ? 'rgba(239,68,68,0.16)' : 'rgba(245,158,11,0.15)'}; border:1px solid ${isCritical ? 'rgba(248,113,113,0.45)' : 'rgba(251,191,36,0.45)'}; color:${isCritical ? '#fecaca' : '#fef08a'}; font-size:11px; line-height:1.35; display:flex; align-items:flex-start; gap:6px;">
            <span style="font-size:12px; line-height:1; flex-shrink:0;">⚠️</span>
            <span>${escapeHtml(warningText)}</span>
          </div>
        ` : `
          <div style="font-size:11px; color:var(--lt-t-cbd5e1ff, #cbd5e1); line-height:1.35; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;" title="${escapeHtml(m.why_recommended || m.use_case || '')}">
            ${escapeHtml(m.use_case || '')}${m.why_recommended ? ` — ${escapeHtml(m.why_recommended)}` : ''}
          </div>
        `}
        <div style="margin-top:auto; padding-top:5px; border-top:1px solid var(--lt-r-ffffff0f, rgba(255,255,255,0.06)); display:flex; justify-content:space-between; align-items:center; gap:6px;">
          <span style="font-size:11px; color:var(--lt-t-94a3b8ff, #94a3b8);">🔋 ${escapeHtml(m.power_profile || 'Low Power')} • 📅 ${escapeHtml(releaseDateText)}</span>
          <div style="display:flex; align-items:center; gap:5px;">
            ${isAct
              ? `<span style="font-size:11px; font-weight:800; color:${hasWarn ? '#fbbf24' : '#34d399'}; padding:2px 8px; border-radius:6px; background:${hasWarn ? 'rgba(245,158,11,0.18)' : 'rgba(16,185,129,0.18)'}; border:1px solid ${hasWarn ? 'rgba(245,158,11,0.45)' : 'rgba(16,185,129,0.4)'};">${hasWarn ? '⚠️ Active (Exceeds HW)' : '✓ Active'}</span>`
              : (m.installed === false && m.ollama_tag && m.ollama_tag !== 'builtin-npu')
                ? `<button type="button" class="btn-pill-toggle btn-ai-install-model is-small" data-model-id="${escapeHtml(m.id)}" data-model-tag="${escapeHtml(m.ollama_tag)}" title="${escapeHtml(t('ai.install_model_title', 'Download this model into Ollama'))}" style="background: var(--lt-b-facc152e, rgba(250,204,21,0.18)); border: 1px solid var(--lt-r-facc157a, rgba(250,204,21,0.48)); color: var(--lt-t-fde047ff, #fde047);">⬇️ ${escapeHtml(t('ai.install_model', 'Install'))}</button>`
              : isLiveHfResult
                ? `<button type="button" class="btn-pill-toggle btn-ai-pull-hf-card" data-hf-repo="${escapeHtml(hfRepo)}" style="font-size:11px; font-weight:700; padding:2px 9px; background:${hasWarn ? 'rgba(245,158,11,0.18)' : 'rgba(250,204,21,0.18)'}; border:1px solid ${hasWarn ? 'rgba(245,158,11,0.5)' : 'rgba(250,204,21,0.48)'}; color:${hasWarn ? '#fbbf24' : '#fde047'}; cursor:pointer;">${hasWarn ? '⚠️ Pull Anyway (Unfit)' : '⬇️ Pull from HF'}</button>`
                : `<button type="button" class="btn-pill-toggle btn-ai-activate-model" data-model-id="${escapeHtml(m.id)}" style="font-size:11px; font-weight:700; padding:2px 9px; background:${hasWarn ? 'rgba(245,158,11,0.16)' : 'rgba(14,165,233,0.18)'}; border:1px solid ${hasWarn ? 'rgba(245,158,11,0.45)' : 'rgba(14,165,233,0.45)'}; color:${hasWarn ? '#fbbf24' : '#38bdf8'}; cursor:pointer;">${hasWarn ? '⚠️ Activate Anyway' : '⚡ Activate'}</button>`
            }
            <button type="button" class="btn-pill-toggle btn-ai-remove-model is-danger is-small" data-model-id="${escapeHtml(m.id)}" data-model-name="${escapeHtml(m.name)}" title="${t('ui.remove_model_from_catalog_and', 'Remove model from catalog and disk')}" aria-label="Remove model ${escapeHtml(m.name)}">🗑️</button>
          </div>
        </div>
      </div>
    `;
  }).join('');

  gridEl.querySelectorAll('.btn-ai-activate-model').forEach((btn) => {
    btn.addEventListener('click', () => {
      const mId = btn.dataset.modelId;
      if (mId) selectAiRecommendedModel(mId);
    });
  });

  gridEl.querySelectorAll('.btn-ai-install-model').forEach((btn) => {
    btn.addEventListener('click', () => installAiModel(btn.dataset.modelTag, btn, btn.dataset.modelId));
  });

  gridEl.querySelectorAll('.btn-ai-pull-hf-card').forEach((btn) => {
    btn.addEventListener('click', () => {
      const repo = btn.dataset.hfRepo;
      if (repo) pullHuggingFaceModel(repo, true);
    });
  });

  gridEl.querySelectorAll('.btn-ai-remove-model').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const mId = btn.dataset.modelId;
      const mName = btn.dataset.modelName || mId;
      if (!mId) return;
      const confirmTitle = t('ai.remove_model_title', 'Remove Model from Catalog');
      const confirmMsg = t(
        'ai.remove_model_confirm',
        `Are you sure you want to remove model "${mName}" from your ZettAI catalog?`
      ).replace('{name}', mName);
      showConfirmToast(
        confirmTitle,
        confirmMsg,
        async () => {
          await removeAiModel(mId);
        }
      );
    });
  });
}

/** Downloads a model into Ollama and shows progress on the button; then offers Activate (AI-03). */
export async function installAiModel(tag, btn = null, modelId = null, { pollMs = 1000 } = {}) {
  if (!tag) return null;
  const label = (txt) => { if (btn) btn.textContent = txt; };
  try {
    if (btn) btn.disabled = true;
    let job = await api.post('/api/ai/models/install', { model: tag });
    while (job && ['starting', 'downloading', 'verifying'].includes(job.state)) {
      label(job.state === 'verifying' ? t('ai.install_verifying', 'Checking…') : `⬇️ ${Math.floor(job.percent || 0)}%`);
      await new Promise((r) => setTimeout(r, pollMs));
      job = await api.get(`/api/ai/models/install/${encodeURIComponent(job.id)}`);
    }
    if (job?.state === 'done') {
      showToast(t('ai.install_done', '{model} installed.', { model: tag }), 'success');
      if (btn) {
        btn.disabled = false;
        btn.classList.remove('btn-ai-install-model');
        btn.textContent = `⚡ ${t('ai.activate', 'Activate')}`;
        btn.onclick = () => selectAiRecommendedModel(modelId || tag);
      }
    } else {
      throw new Error(job?.error || job?.status || 'Install failed');
    }
    return job;
  } catch (err) {
    showToast(t('toast.ai_install_failed', 'Could not install model: {error}', { error: err.message }), 'error');
    if (btn) { btn.disabled = false; label(`⬇️ ${t('ai.install_model', 'Install')}`); }
    return null;
  }
}

export async function removeAiModel(modelId) {
  const cleanId = String(modelId || '').trim();
  if (!cleanId) return null;
  try {
    let res = null;
    try {
      res = await api.post('/api/media/models/remove', { model: cleanId, model_id: cleanId });
    } catch (postErr) {
      try {
        res = await api.post('/api/ai/models/remove', { model: cleanId, model_id: cleanId });
      } catch {
        res = await api.delete(`/api/media/models/${encodeURIComponent(cleanId)}`);
      }
    }
    if (res) {
      const recs = res.llm_recommendations || res.recommendations;
      if (recs) {
        renderAiLlmRecommendations(recs, res.active_model);
      }
      showToast(t('ai.model_removed_toast', `Model "${cleanId}" removed from catalog`), 'success');
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    showToast(t('toast.failed_to_remove_model', 'Failed to remove model: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function selectAiRecommendedModel(modelId) {
  const cleanId = String(modelId || '').trim();
  if (!cleanId) return null;
  try {
    const res = await api.post('/api/media/models/select', { model: cleanId, model_id: cleanId });
    if (res) {
      const recs = res.llm_recommendations || res.recommendations;
      if (recs) {
        renderAiLlmRecommendations(recs, res.active_model || cleanId);
      }
      if (res.hardware_warning && res.warning_message) {
        showToast(t('toast.message_2', '⚠️ {warning_message}', { warning_message: res.warning_message }), 'warn');
      } else {
        showToast(t('ai.model_selected_toast', 'Active ZettAI model switched to {model}', { model: cleanId }), 'success');
      }
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    showToast(t('toast.failed_to_select_model', 'Failed to select model: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function searchHuggingFaceModels(query = '') {
  const statusEl = document.getElementById('ai-hf-search-status');
  const resetBtn = document.getElementById('btn-ai-hf-reset');
  const cleanQ = String(query || '').trim();
  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.textContent = `🤗 Searching https://huggingface.co release models${cleanQ ? ` for "${cleanQ}"` : ''}...`;
  }
  try {
    const res = await api.get(`/api/media/models/huggingface/search?q=${encodeURIComponent(cleanQ)}&limit=18`);
    if (res && Array.isArray(res.models)) {
      const warnCount = res.models.filter((m) => m.fits_hardware === false || m.hardware_warning).length;
      if (statusEl) {
        statusEl.textContent = `🤗 Showing ${res.models.length} Hugging Face release models (${res.models.length - warnCount} fit your hardware, ${warnCount} flagged with hardware warning).`;
      }
      if (resetBtn) {
        resetBtn.style.display = 'inline-block';
      }
      renderAiLlmRecommendations(
        {
          headline: _aiLastLlmRecommendations?.headline || 'Hugging Face Hub Search',
          hardware_summary: _aiLastLlmRecommendations?.hardware_summary || '',
          active_model: _aiLastActiveModel,
          models: res.models,
        },
        _aiLastActiveModel
      );
    }
    return res;
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = `⚠️ Hugging Face Hub search error: ${err.message}`;
    }
    showToast(t('toast.hugging_face_search_failed', 'Hugging Face search failed: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function pullHuggingFaceModel(repoId, activate = true) {
  const cleanRepo = String(repoId || '').trim();
  if (!cleanRepo) {
    showToast(t('toast.enter_a_hugging_face_model_repo', 'Enter a Hugging Face model repo or URL (e.g. Qwen/Qwen2.5-7B-Instruct-GGUF)'), 'warn');
    return null;
  }
  const statusEl = document.getElementById('ai-hf-search-status');
  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.textContent = `⬇️ Pulling release model metadata from https://huggingface.co/${cleanRepo.replace(/^https?:\/\/huggingface\.co\//i, '')}...`;
  }
  try {
    const res = await api.post('/api/media/models/huggingface/pull', {
      repo_id: cleanRepo,
      activate: Boolean(activate),
    });
    if (res) {
      if (res.llm_recommendations) {
        renderAiLlmRecommendations(res.llm_recommendations, res.active_model || res.model?.id);
      }
      if (res.hardware_warning && res.warning_message) {
        if (statusEl) {
          statusEl.textContent = `⚠️ Pulled ${res.model?.hf_repo || cleanRepo} — ${res.warning_message}`;
        }
        showToast(t('toast.hf_pulled_warning', '⚠️ Added {model}: {warning}', { model: res.model?.name || cleanRepo, warning: res.warning_message }), 'warn');
      } else {
        if (statusEl) {
          statusEl.textContent = `✅ Pulled ${res.model?.hf_repo || cleanRepo} from Hugging Face (Fits your hardware).`;
        }
        showToast(t('toast.hf_pulled', '🤗 Added and selected {model} from Hugging Face', { model: res.model?.name || cleanRepo }), 'success');
      }
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = `⚠️ Failed to pull from Hugging Face: ${err.message}`;
    }
    showToast(t('toast.failed_to_pull_model_from_hugging', 'Failed to pull model from Hugging Face: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function updateAiServiceConfig(partialConfig = {}) {
  try {
    const res = await api.put('/api/media/config', partialConfig);
    await fetchAndRenderAiStatus();
    return res;
  } catch (err) {
    showToast(t('toast.failed_to_update_zettai_configuration', 'Failed to update ZettAI configuration: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function openAiLearningResults() {
  const panel = document.getElementById('ai-learning-results-panel');
  const indexTab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-ai-index"]');
  if (indexTab && !indexTab.classList.contains('active')) {
    indexTab.click();
  }
  if (panel) {
    panel.style.display = 'block';
  }
  try {
    const res = await api.get('/api/media/learning/results');
    if (res) {
      renderAiLearningResultsData(res);
    }
    return res;
  } catch (err) {
    return null;
  }
}

export function renderAiLearningResultsData(data = {}) {
  const succEl = document.getElementById('ai-learn-succeeded-count');
  const failEl = document.getElementById('ai-learn-failed-count');
  const defEl = document.getElementById('ai-learn-deferred-count');
  const listEl = document.getElementById('ai-learn-failed-list');

  if (succEl) succEl.textContent = String(data.succeeded_count ?? 0);
  if (failEl) failEl.textContent = String(data.failed_count ?? 0);
  if (defEl) defEl.textContent = String(data.deferred_standby_count ?? 0);

  if (listEl) {
    const failedFiles = Array.isArray(data.failed_files) ? data.failed_files : [];
    if (failedFiles.length === 0) {
      listEl.innerHTML = `<div style="padding:8px 10px; border-radius:6px; background:rgba(34,197,94,0.08); color:var(--lt-t-86efacff, #86efac);">✓ All learned files succeeded with 0 errors.</div>`;
    } else {
      listEl.innerHTML = failedFiles.map((f) => `
        <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; padding:6px 8px; border-bottom:1px solid var(--lt-r-ffffff0f, rgba(255,255,255,0.06));">
          <span style="font-family:monospace; color:var(--lt-t-fca5a5ff, #fca5a5);">${escapeHtml(f.file_path || f.file_name || '')}</span>
          <span style="color:var(--lt-t-94a3b8ff, #94a3b8); font-size:11px;">${escapeHtml(f.error || 'Failed to parse')}</span>
        </div>
      `).join('');
    }
  }
}

export async function relearnAiFailedFiles() {
  try {
    const res = await api.post('/api/media/learning/relearn-failed', {});
    if (res) {
      showToast(t('toast.relearned', 'Relearned {count} file(s) ({remaining} remaining).', { count: res.relearned ?? 0, remaining: res.still_failed ?? 0 }), 'success');
      await openAiLearningResults();
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    showToast(t('toast.relearn_failed', 'Relearn failed: {error}', { error: err.message }), 'error');
    return null;
  }
}

export function updateAiSyncProgressUi(syncProg = {}, standbyGuard = {}, zettaiStatus = '') {
  const state = String(syncProg.state || 'idle').toLowerCase();
  const isRunning = state === 'running' || Boolean(syncProg.is_scanning);
  const isPaused = state === 'paused' || Boolean(syncProg.is_paused);
  const isStopped = state === 'stopped';
  const isDisabled = String(zettaiStatus || '').toLowerCase() === 'disabled' || syncProg.enabled === false;
  const isComplete = !isRunning && !isPaused && !isStopped && !isDisabled && (
    state === 'completed' ||
    Number(syncProg.indexed_files || 0) > 0 ||
    Number(syncProg.skipped_unchanged || 0) > 0 ||
    String(syncProg.last_message || '').toLowerCase().includes('synced') ||
    String(syncProg.last_message || '').toLowerCase().includes('complete')
  );

  const stateBadge = document.getElementById('ai-sync-state-badge');
  const stateDot = document.getElementById('ai-sync-state-dot');
  const stateText = document.getElementById('ai-sync-state-text');
  if (stateDot && stateText && stateBadge) {
    if (isDisabled) {
      stateDot.style.background = '#64748b';
      stateText.textContent = t('ai.sync_state_disabled', 'Status: Disabled');
      stateBadge.style.borderColor = 'rgba(100,116,139,0.4)';
      stateBadge.style.color = '#94a3b8';
    } else if (isPaused) {
      stateDot.style.background = '#fbbf24';
      stateText.textContent = t('ai.sync_state_paused', 'Sync: Paused');
      stateBadge.style.borderColor = 'rgba(245,158,11,0.45)';
      stateBadge.style.color = '#fde68a';
    } else if (isRunning) {
      stateDot.style.background = '#34d399';
      stateText.textContent = t('ai.sync_state_running', 'Sync: Learning');
      stateBadge.style.borderColor = 'rgba(52,211,153,0.45)';
      stateBadge.style.color = '#6ee7b7';
    } else if (isStopped) {
      stateDot.style.background = '#f87171';
      stateText.textContent = t('ai.sync_state_stopped', 'Sync: Stopped');
      stateBadge.style.borderColor = 'rgba(248,113,113,0.45)';
      stateBadge.style.color = '#fca5a5';
    } else if (isComplete) {
      stateDot.style.background = '#10b981';
      stateText.textContent = t('ai.sync_state_complete', 'Sync: Complete (Up to Date)');
      stateBadge.style.borderColor = 'rgba(16,185,129,0.45)';
      stateBadge.style.color = '#6ee7b7';
    } else {
      stateDot.style.background = '#94a3b8';
      stateText.textContent = t('ai.sync_state_idle', 'Sync: Idle');
      stateBadge.style.borderColor = 'rgba(148,163,184,0.28)';
      stateBadge.style.color = '#cbd5e1';
    }
  }

  // Ribbon transport buttons
  const ribPause = document.getElementById('btn-ai-sync-pause');
  const ribResume = document.getElementById('btn-ai-sync-resume');
  const ribStop = document.getElementById('btn-ai-sync-stop');
  if (ribPause) ribPause.style.display = (isRunning && !isPaused) ? 'inline-flex' : 'none';
  if (ribResume) ribResume.style.display = isPaused ? 'inline-flex' : 'none';
  if (ribStop) ribStop.style.display = (isRunning || isPaused) ? 'inline-flex' : 'none';

  // Indexer pane transport buttons
  const idxPause = document.getElementById('btn-ai-index-pause');
  const idxResume = document.getElementById('btn-ai-index-resume');
  const idxStop = document.getElementById('btn-ai-index-stop');
  if (idxPause) {
    idxPause.disabled = !(isRunning && !isPaused);
    idxPause.style.opacity = (isRunning && !isPaused) ? '1' : '0.45';
  }
  if (idxResume) {
    idxResume.disabled = !isPaused;
    idxResume.style.opacity = isPaused ? '1' : '0.45';
  }
  if (idxStop) {
    idxStop.disabled = !(isRunning || isPaused);
    idxStop.style.opacity = (isRunning || isPaused) ? '1' : '0.45';
  }

  // Progress banner
  const statePill = document.getElementById('ai-index-sync-state-pill');
  if (statePill) {
    const pillLabel = isDisabled
      ? 'DISABLED'
      : isPaused
        ? 'PAUSED'
        : isRunning
          ? 'LEARNING'
          : isStopped
            ? 'STOPPED'
            : isComplete
              ? 'COMPLETE'
              : (zettaiStatus ? String(zettaiStatus).toUpperCase() : 'IDLE');
    statePill.textContent = pillLabel;
    statePill.style.background = isPaused
      ? 'rgba(245,158,11,0.22)'
      : isRunning
        ? 'rgba(37,194,160,0.22)'
        : isStopped
          ? 'rgba(239,68,68,0.22)'
          : isComplete
            ? 'rgba(16,185,129,0.22)'
            : 'rgba(148,163,184,0.18)';
    statePill.style.color = isPaused ? '#fbbf24' : isRunning ? '#34d399' : isStopped ? '#f87171' : isComplete ? '#34d399' : '#e2e8f0';
  }

  const curPathEl = document.getElementById('ai-index-current-path');
  if (curPathEl) {
    let msg = syncProg.last_message || syncProg.current_path || 'Ready — Waiting for sync command (Sleeping drives protected)';
    if (syncProg.updated_at && (!syncProg.state || syncProg.state === 'idle' || syncProg.state === 'completed')) {
      try {
        const timeStr = formatTime(syncProg.updated_at, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        if (!msg.includes('Finished at') && !msg.includes('Completed at')) {
          msg += ` (Finished at ${timeStr})`;
        }
      } catch (_) {}
    }
    curPathEl.textContent = msg;
  }

  const progIdx = document.getElementById('ai-prog-indexed');
  const progUnch = document.getElementById('ai-prog-unchanged');
  const progDef = document.getElementById('ai-prog-deferred');
  if (progIdx) progIdx.textContent = String(syncProg.indexed_files ?? 0);
  if (progUnch) progUnch.textContent = String(syncProg.skipped_unchanged ?? 0);
  if (progDef) progDef.textContent = String(syncProg.deferred_standby ?? 0);

  const guardText = document.getElementById('ai-standby-guard-text');
  const guardBadge = document.getElementById('ai-standby-guard-badge');
  if (guardText && standbyGuard) {
    const sleepCnt = Number(standbyGuard.sleeping_disks_count || 0);
    const runCnt = Number(standbyGuard.running_disks_count || 0);
    if (sleepCnt > 0 || runCnt > 0) {
      guardText.textContent = `Standby Guard (${runCnt} Active, ${sleepCnt} Sleeping)`;
      if (guardBadge) {
        guardBadge.title = `Standby Guard: Active (0 Wakeups • ${runCnt} Running, ${sleepCnt} Sleeping)`;
      }
    }
  }

  _ensureAiSyncPoll(isRunning || isPaused);
}

export function setAiWatchedFoldersDropdownOpen(forceOpen = null) {
  const menu = document.getElementById('ai-watched-folders-dropdown-menu');
  const btn = document.getElementById('btn-ai-watched-folders-dropdown');
  const caret = document.getElementById('ai-watched-dropdown-caret');
  if (!menu) return false;
  const isCurrentlyOpen = menu.style.display !== 'none';
  const nextOpen = forceOpen !== null ? Boolean(forceOpen) : !isCurrentlyOpen;
  menu.style.display = nextOpen ? 'block' : 'none';
  if (btn) {
    btn.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
    btn.style.borderColor = nextOpen ? 'rgba(56,189,248,0.75)' : 'rgba(56,189,248,0.4)';
  }
  if (caret) {
    caret.textContent = nextOpen ? '▴' : '▾';
  }
  return nextOpen;
}

/** Deletes what the index learned from a folder and stops learning it (AI-20). The server asks to confirm. */
export async function forgetAiFolder(folderPath) {
  try {
    const res = await api.post('/api/ai/index/forget', { path: folderPath });
    _aiWatchedPaths = _aiWatchedPaths.filter((p) => p !== folderPath);
    renderAiWatchedFoldersAndShares();
    const n = res?.removed?.files ?? 0;
    showToast(t('ai.forget_folder_done', "Forgot {count} file(s) from {folder}. It won't be learned again.", { count: n, folder: folderPath }), 'success');
    return res;
  } catch (err) {
    if (err?.error !== 'cancelled') showToast(t('toast.ai_forget_failed', 'Could not forget folder: {error}', { error: err.message }), 'error');
    return null;
  }
}

export function renderAiWatchedFoldersAndShares(watchedPaths = null, availableFolders = null) {
  if (Array.isArray(watchedPaths)) {
    _aiWatchedPaths = watchedPaths;
  }
  if (Array.isArray(availableFolders)) {
    _aiAvailableFolders = availableFolders;
  }

  const folderMap = new Map(_aiAvailableFolders.map((f) => [f.path, f]));
  const mergedFolders = [..._aiAvailableFolders];
  _aiWatchedPaths.forEach((fp) => {
    if (fp && !folderMap.has(fp)) {
      const customEntry = { path: fp, in_standby: false, backing_dev: '' };
      folderMap.set(fp, customEntry);
      mergedFolders.push(customEntry);
    }
  });

  // Update dropdown trigger summary & checked count badge
  const summaryEl = document.getElementById('ai-watched-dropdown-summary');
  const countBadgeEl = document.getElementById('ai-watched-dropdown-count-badge');
  if (summaryEl) {
    summaryEl.textContent = _aiWatchedPaths.length > 0
      ? _aiWatchedPaths.join(', ')
      : 'No folders checked — click to select folders for RAG';
  }
  if (countBadgeEl) {
    countBadgeEl.textContent = `${_aiWatchedPaths.length} Checked`;
  }

  // Render compact checked chips below dropdown
  const watchedContainer = document.getElementById('ai-watched-folders-list');
  if (watchedContainer) {
    watchedContainer.innerHTML = _aiWatchedPaths.map((fp) => {
      const info = folderMap.get(fp);
      const inStandby = Boolean(info?.in_standby);
      const dev = info?.backing_dev || '';
      return `
        <div class="ai-watched-folder-chip" data-folder-path="${escapeHtml(fp)}" style="display:inline-flex; align-items:center; gap:7px; padding:4px 9px; border-radius:8px; background:rgba(14,165,233,0.14); border:1px solid rgba(14,165,233,0.38); font-size:11px; color:var(--lt-t-f8fafcff, #f8fafc);">
          <span aria-hidden="true">☑</span>
          <span style="font-family:monospace; font-weight:700;">${escapeHtml(fp)}</span>
          <span style="font-size:11px; padding:1px 6px; border-radius:999px; background:${inStandby ? 'rgba(245,158,11,0.18)' : 'rgba(37,194,160,0.18)'}; color:${inStandby ? '#fbbf24' : '#34d399'};">
            ${inStandby ? `💤 Standby${dev ? ` (${escapeHtml(dev)})` : ''}` : `🟢 Running${dev ? ` (${escapeHtml(dev)})` : ''}`}
          </span>
          <button type="button" class="btn-ai-sync-single-folder" data-folder-path="${escapeHtml(fp)}" title="${t('ui.sync_this_folder_now_standby', 'Sync this folder now (Standby Safe)')}" style="background:transparent; border:none; color:var(--lt-t-38bdf8ff, #38bdf8); cursor:pointer; font-size:11px; padding:0 2px;">🔄</button>
          <button type="button" class="btn-ai-remove-watched-folder" data-folder-path="${escapeHtml(fp)}" title="${t('ui.uncheck_folder_from_rag_watched', 'Uncheck folder from RAG watched list')}" style="background:transparent; border:none; color:var(--lt-t-f87171ff, #f87171); cursor:pointer; font-size:11px; font-weight:800; padding:0 2px;">✕</button>
          <button type="button" class="btn-ai-forget-folder" data-folder-path="${escapeHtml(fp)}" title="${escapeHtml(t('ai.forget_folder_title', 'Forget: delete everything the AI learned from this folder'))}" aria-label="${escapeHtml(t('ai.forget_folder_title', 'Forget: delete everything the AI learned from this folder'))}" style="background:transparent; border:none; color:var(--lt-t-fca5a5ff, #fca5a5); cursor:pointer; font-size:11px; padding:0 2px;">🗑</button>
        </div>
      `;
    }).join('');

    watchedContainer.querySelectorAll('.btn-ai-sync-single-folder').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const fp = btn.dataset.folderPath;
        const respectCb = document.getElementById('ai-index-respect-standby') || document.getElementById('ai-respect-standby-cb');
        if (fp) {
          const pathIn = document.getElementById('ai-index-target-path') || document.getElementById('ai-index-path-input');
          if (pathIn) pathIn.value = fp;
          runAiPathIndex(fp, respectCb ? Boolean(respectCb.checked) : true);
        }
      });
    });

    watchedContainer.querySelectorAll('.btn-ai-forget-folder').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const fp = btn.dataset.folderPath;
        if (fp) forgetAiFolder(fp);
      });
    });

    watchedContainer.querySelectorAll('.btn-ai-remove-watched-folder').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const fp = btn.dataset.folderPath;
        if (fp) removeAiWatchedFolder(fp);
      });
    });
  }

  // Render dropdown multi-select checklist of all available folders
  const sharesContainer = document.getElementById('ai-discovered-shares-list');
  if (sharesContainer) {
    if (mergedFolders.length === 0) {
      sharesContainer.innerHTML = `<span style="font-size:11px; color:var(--muted); padding:6px 8px;">No NAS folders discovered yet. Use Browse or Add Folder below.</span>`;
    } else {
      sharesContainer.innerHTML = mergedFolders.map((f) => {
        const isWatched = _aiWatchedPaths.includes(f.path);
        const inStandby = Boolean(f.in_standby);
        const dev = f.backing_dev || '';
        return `
          <div role="option" aria-selected="${isWatched ? 'true' : 'false'}" class="btn-pill-toggle ai-discovered-share-pill ai-watched-dropdown-item ${isWatched ? 'active' : ''}" data-folder-path="${escapeHtml(f.path)}" data-watched="${isWatched ? '1' : '0'}" style="display:flex; align-items:center; justify-content:space-between; gap:8px; width:100%; box-sizing:border-box; font-size:11.5px; padding:7px 10px; border-radius:8px; background:${isWatched ? 'rgba(37,194,160,0.16)' : 'rgba(255,255,255,0.03)'}; border:1px solid ${isWatched ? 'rgba(37,194,160,0.48)' : 'rgba(255,255,255,0.08)'}; color:${isWatched ? '#fff' : '#cbd5e1'}; cursor:pointer; text-align:left;" title="${inStandby ? `Backing disk (${dev}) is in STANDBY — will only sync when disk is running` : `Backing disk (${dev || 'NVMe/Pool'}) is RUNNING — click to check/uncheck for RAG`}">
            <div style="display:flex; align-items:center; gap:8px; min-width:0; flex:1;">
              <span class="ai-folder-checkbox-icon" style="display:inline-flex; align-items:center; justify-content:center; width:16px; height:16px; border-radius:4px; background:${isWatched ? '#10b981' : 'rgba(255,255,255,0.08)'}; border:1px solid ${isWatched ? '#34d399' : 'rgba(255,255,255,0.28)'}; color:#042f2e; font-size:11px; font-weight:900; flex-shrink:0;">${isWatched ? '✓' : ''}</span>
              <span aria-hidden="true">📁</span>
              <span style="font-family:monospace; font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(f.path)}</span>
            </div>
            <div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">
              <span style="font-size:11px; padding:1px 7px; border-radius:999px; background:${inStandby ? 'rgba(245,158,11,0.16)' : 'rgba(37,194,160,0.16)'}; color:${inStandby ? '#fbbf24' : '#34d399'};">
                ${inStandby ? `💤 ${escapeHtml(dev || 'Standby')}` : `🟢 ${escapeHtml(dev || 'Running')}`}
              </span>
              <span style="font-size:11px; font-weight:700; padding:1px 6px; border-radius:6px; background:${isWatched ? 'rgba(16,185,129,0.22)' : 'rgba(255,255,255,0.06)'}; color:${isWatched ? '#6ee7b7' : '#94a3b8'};">
                ${isWatched ? 'RAG Checked' : 'Click to Add'}
              </span>
            </div>
          </div>
        `;
      }).join('');

      sharesContainer.querySelectorAll('.ai-discovered-share-pill').forEach((pill) => {
        pill.addEventListener('click', (e) => {
          e.stopPropagation();
          const fp = pill.dataset.folderPath;
          const isWatched = pill.dataset.watched === '1';
          if (!fp) return;
          if (isWatched) {
            removeAiWatchedFolder(fp);
          } else {
            addAiWatchedFolder(fp);
          }
        });
      });
    }
  }
}

export async function controlAiSync(action) {
  const cleanAction = String(action || '').trim().toLowerCase();
  if (!cleanAction) return null;
  if (cleanAction === 'flush' || cleanAction === 'clear') {
    return flushAiIndex();
  }
  const feedbackEl = document.getElementById('ai-index-run-feedback');
  try {
    const res = await api.post('/api/media/index/control', { action: cleanAction });
    if (res) {
      await fetchAndRenderAiStatus();
      updateAiSyncProgressUi(res.sync_progress || { state: res.sync_state || cleanAction });
      const label = cleanAction === 'pause'
        ? t('ai.sync_paused_toast', 'Indexing sync paused.')
        : cleanAction === 'resume'
          ? t('ai.sync_resumed_toast', 'Indexing sync resumed (standby disks protected).')
          : t('ai.sync_stopped_toast', 'Indexing sync stopped.');
      if (feedbackEl) feedbackEl.textContent = `ℹ️ ${label}`;
      showToast(label, cleanAction === 'stop' ? 'warn' : 'info');
    }
    return res;
  } catch (err) {
    showToast(t('toast.sync_control_failed', 'Sync control ({cleanAction}) failed: {error}', { cleanAction: cleanAction, error: err.message }), 'error');
    return null;
  }
}

export async function flushAiIndex() {
  showConfirmToast(
    t('ai.flush_index_confirm_title', 'Flush RAG Index & Start Fresh?'),
    t(
      'ai.flush_index_confirm_desc',
      'Are you sure you want to flush the existing RAG knowledge base? This will wipe all indexed documents, code files, recipes, photos, vector embeddings, and cached search manifests from rag_index.db so you can perform a clean fresh sync.'
    ),
    async () => {
      const feedbackEl = document.getElementById('ai-index-run-feedback');
      if (feedbackEl) feedbackEl.textContent = t('ui.flushing_rag_index_database', '⏳ Flushing RAG index database...');
      showToast(t('toast.flushing_rag_index_database', 'Flushing RAG index database...'), 'info');
      try {
        const res = await api.post('/api/ai/index/flush');
        await fetchAndRenderAiStatus();
        if (feedbackEl) feedbackEl.textContent = t('ui.rag_database_flushed_clean_ready', '✓ RAG database flushed clean. Ready for fresh sync.');
        showToast(
          t('ai.flush_index_success_toast', 'RAG index database successfully flushed clean. Ready for fresh sync.'),
          'success'
        );
        return res;
      } catch (err) {
        if (feedbackEl) feedbackEl.textContent = `✕ Flush failed: ${err.message}`;
        showToast(t('toast.failed_to_flush_rag_index', 'Failed to flush RAG index: {error}', { error: err.message }), 'error');
        return null;
      }
    },
    null,
    {
      okText: '🗑️ Flush & Reset',
      cancelText: 'Cancel',
      isDanger: true,
    }
  );
}

export async function addAiWatchedFolder(folderPath) {
  const fp = String(folderPath || '').trim();
  if (!fp) {
    showToast(t('ai.enter_folder_path', 'Please enter or browse a folder path to add.'), 'warn');
    return null;
  }
  try {
    const res = await api.post('/api/media/folders', { action: 'add', path: fp });
    if (res) {
      renderAiWatchedFoldersAndShares(res.watched_paths || [], res.available_folders || _aiAvailableFolders);
      if (res.sync_progress) {
        updateAiSyncProgressUi(res.sync_progress);
      }
      const pathIn = document.getElementById('ai-index-target-path') || document.getElementById('ai-index-path-input');
      if (pathIn) pathIn.value = fp;
      showToast(t('toast.added_watched_folder', 'Added watched folder: {fp}', { fp: fp }), 'success');
    }
    return res;
  } catch (err) {
    showToast(t('toast.failed_to_add_folder', 'Failed to add folder: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function removeAiWatchedFolder(folderPath) {
  const fp = String(folderPath || '').trim();
  if (!fp) return null;
  try {
    const res = await api.post('/api/media/folders', { action: 'remove', path: fp });
    if (res) {
      renderAiWatchedFoldersAndShares(res.watched_paths || [], res.available_folders || _aiAvailableFolders);
      if (res.sync_progress) {
        updateAiSyncProgressUi(res.sync_progress);
      }
      showToast(t('toast.removed_watched_folder', 'Removed watched folder: {fp}', { fp: fp }), 'info');
    }
    return res;
  } catch (err) {
    showToast(t('toast.failed_to_remove_folder', 'Failed to remove folder: {error}', { error: err.message }), 'error');
    return null;
  }
}

export async function syncAiWatchedFolders(respectStandby = true, background = true) {
  const feedbackEl = document.getElementById('ai-index-run-feedback');
  const pathsToSync = Array.isArray(_aiWatchedPaths) && _aiWatchedPaths.length > 0 ? _aiWatchedPaths : ['/mnt/user'];
  if (feedbackEl) {
    feedbackEl.textContent = `⏳ Starting spindown-safe sync across ${pathsToSync.length} watched folder(s)...`;
  }
  try {
    const res = await api.post('/api/media/index', {
      paths: pathsToSync,
      respect_standby: Boolean(respectStandby),
      recursive: true,
      background: Boolean(background),
    });
    if (res) {
      if (res.sync_progress) {
        updateAiSyncProgressUi(res.sync_progress);
      }
      if (res.status === 'started') {
        const msg = `Sync started on ${pathsToSync.join(', ')} (Active disks only — sleeping drives protected).`;
        if (feedbackEl) feedbackEl.textContent = `🔄 ${msg}`;
        showToast(msg, 'info');
        _ensureAiSyncPoll(true);
      } else {
        const indexedCount = res.indexed ?? res.indexed_files ?? 0;
        const skippedCount = res.skipped_unchanged ?? 0;
        const deferredCount = res.deferred_standby ?? 0;
        const msg = deferredCount > 0
          ? `Indexed ${indexedCount} file(s), ${skippedCount} unchanged (${deferredCount} deferred to protect sleeping drives).`
          : `Indexed ${indexedCount} file(s) (${skippedCount} unchanged).`;
        if (feedbackEl) feedbackEl.textContent = `✓ ${msg}`;
        showToast(msg, 'success');
      }
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    if (feedbackEl) feedbackEl.textContent = `⚠️ Sync failed: ${err.message}`;
    showToast(t('toast.sync_failed', 'Sync failed: {error}', { error: err.message }), 'error');
    return null;
  }
}

export function _getActiveAiSearchQuery() {
  const visInput = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
  if (visInput && visInput.value.trim()) return visInput.value.trim();
  const askInput = document.getElementById('ai-rag-query-input');
  return askInput ? askInput.value.trim() : '';
}

export function initAiKnowledgeEngine() {
  import('../model-bench.js').then((m) => m.renderModelBench()).catch(() => {}); // D2
  renderAiSearchHistory();

  const topbarPill = document.getElementById('topbar-ai-accel-pill');
  if (topbarPill && !topbarPill.dataset.bound) {
    topbarPill.dataset.bound = '1';
    topbarPill.addEventListener('click', () => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-ai', 'mgmt-pane-ai-index');
      }
    });
  }

  // Collapsible Color & Scene Visual Filters Drawer toggle (#btn-ai-toggle-visual-filters)
  const toggleFiltersBtn = document.getElementById('btn-ai-toggle-visual-filters');
  if (toggleFiltersBtn && !toggleFiltersBtn.dataset.bound) {
    toggleFiltersBtn.dataset.bound = '1';
    toggleFiltersBtn.addEventListener('click', () => {
      setAiVisualFiltersDrawerOpen();
    });
  }

  // ZettAI Master Switch (#ai-master-enable-toggle)
  const masterToggle = document.getElementById('ai-master-enable-toggle');
  if (masterToggle && !masterToggle.dataset.bound) {
    masterToggle.dataset.bound = '1';
    masterToggle.addEventListener('change', async () => {
      const enabled = Boolean(masterToggle.checked);
      await updateAiServiceConfig({ enabled });
      showToast(
        enabled
          ? t('ai.service_enabled_toast', 'ZettAI service enabled — AI learning & search active.')
          : t('ai.service_disabled_toast', 'ZettAI service disabled — unfinished learning tasks paused.'),
        enabled ? 'success' : 'warn'
      );
    });
  }

  // Model Selector (#ai-top-model-select)
  const topModelSelect = document.getElementById('ai-top-model-select');
  if (topModelSelect && !topModelSelect.dataset.bound) {
    topModelSelect.dataset.bound = '1';
    topModelSelect.addEventListener('change', () => {
      if (topModelSelect.value) {
        selectAiRecommendedModel(topModelSelect.value);
      }
    });
  }

  // Hugging Face Hub Search, Pull & Hardware Filter Pills
  const hfSearchInput = document.getElementById('ai-hf-search-input');
  const hfSearchBtn = document.getElementById('btn-ai-hf-search');
  const hfPullBtn = document.getElementById('btn-ai-hf-pull');
  const hfResetBtn = document.getElementById('btn-ai-hf-reset');

  if (hfSearchBtn && !hfSearchBtn.dataset.bound) {
    hfSearchBtn.dataset.bound = '1';
    hfSearchBtn.addEventListener('click', () => {
      searchHuggingFaceModels(hfSearchInput ? hfSearchInput.value : '');
    });
  }
  if (hfPullBtn && !hfPullBtn.dataset.bound) {
    hfPullBtn.dataset.bound = '1';
    hfPullBtn.addEventListener('click', () => {
      pullHuggingFaceModel(hfSearchInput ? hfSearchInput.value : '', true);
    });
  }
  if (hfSearchInput && !hfSearchInput.dataset.bound) {
    hfSearchInput.dataset.bound = '1';
    hfSearchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        searchHuggingFaceModels(hfSearchInput.value);
      }
    });
  }
  if (hfResetBtn && !hfResetBtn.dataset.bound) {
    hfResetBtn.dataset.bound = '1';
    hfResetBtn.addEventListener('click', () => {
      if (hfSearchInput) hfSearchInput.value = '';
      hfResetBtn.style.display = 'none';
      const statusEl = document.getElementById('ai-hf-search-status');
      if (statusEl) statusEl.style.display = 'none';
      _aiActiveHfFilter = 'all';
      fetchAndRenderAiStatus();
    });
  }
  document.querySelectorAll('.ai-hf-filter-btn').forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => {
      _aiActiveHfFilter = btn.dataset.hfFilter || 'all';
      if (_aiLastLlmRecommendations) {
        renderAiLlmRecommendations(_aiLastLlmRecommendations, _aiLastActiveModel);
      }
    });
  });

  // Learning Results button (#btn-ai-learning-results), Close & Relearn Failed
  const learnResBtn = document.getElementById('btn-ai-learning-results');
  if (learnResBtn && !learnResBtn.dataset.bound) {
    learnResBtn.dataset.bound = '1';
    learnResBtn.addEventListener('click', () => {
      openAiLearningResults();
    });
  }
  const closeLearnResBtn = document.getElementById('btn-ai-close-learning-results');
  if (closeLearnResBtn && !closeLearnResBtn.dataset.bound) {
    closeLearnResBtn.dataset.bound = '1';
    closeLearnResBtn.addEventListener('click', () => {
      const panel = document.getElementById('ai-learning-results-panel');
      if (panel) panel.style.display = 'none';
    });
  }
  const relearnBtn = document.getElementById('btn-ai-relearn-failed');
  if (relearnBtn && !relearnBtn.dataset.bound) {
    relearnBtn.dataset.bound = '1';
    relearnBtn.addEventListener('click', () => {
      relearnAiFailedFiles();
    });
  }

  // Learning Scope Mode (#ai-learning-scope-mode) & Scheduled Learning Window
  const scopeModeSelect = document.getElementById('ai-learning-scope-mode');
  if (scopeModeSelect && !scopeModeSelect.dataset.bound) {
    scopeModeSelect.dataset.bound = '1';
    scopeModeSelect.addEventListener('change', async () => {
      await updateAiServiceConfig({ scope_mode: scopeModeSelect.value });
      showToast(t('toast.learning_scope_updated', 'Learning scope: {scope}', { scope: scopeModeSelect.options[scopeModeSelect.selectedIndex]?.text || scopeModeSelect.value }), 'info');
    });
  }

  const saveSchedBtn = document.getElementById('btn-ai-save-schedule');
  const schedToggle = document.getElementById('ai-schedule-enabled-toggle');
  const saveScheduleHandler = async () => {
    const schedule_enabled = Boolean(document.getElementById('ai-schedule-enabled-toggle')?.checked);
    const schedule_start = document.getElementById('ai-schedule-start-input')?.value || '01:00';
    const schedule_end = document.getElementById('ai-schedule-end-input')?.value || '06:00';
    await updateAiServiceConfig({ schedule_enabled, schedule_start, schedule_end });
    showToast(
      schedule_enabled
        ? `Scheduled AI learning active (${schedule_start} – ${schedule_end}).`
        : 'Scheduled AI learning window disabled (real-time learning active).',
      'success'
    );
  };
  if (saveSchedBtn && !saveSchedBtn.dataset.bound) {
    saveSchedBtn.dataset.bound = '1';
    saveSchedBtn.addEventListener('click', saveScheduleHandler);
  }
  if (schedToggle && !schedToggle.dataset.bound) {
    schedToggle.dataset.bound = '1';
    schedToggle.addEventListener('change', saveScheduleHandler);
  }

  // Clear Search History (#btn-ai-clear-history)
  const clearHistBtn = document.getElementById('btn-ai-clear-history');
  if (clearHistBtn && !clearHistBtn.dataset.bound) {
    clearHistBtn.dataset.bound = '1';
    clearHistBtn.addEventListener('click', () => {
      _aiSearchHistory = [];
      try { localStorage.removeItem('zettnas_ai_search_history'); } catch (_) {}
      renderAiSearchHistory();
    });
  }

  const refreshBtn = document.getElementById('btn-ai-refresh-status');
  if (refreshBtn && !refreshBtn.dataset.bound) {
    refreshBtn.dataset.bound = '1';
    refreshBtn.addEventListener('click', () => {
      fetchAndRenderAiStatus();
      showToast(t('ai.status_refreshed', 'AI engine telemetry refreshed.'), 'info');
    });
  }

  const syncIndexBtn = document.getElementById('btn-ai-sync-index');
  if (syncIndexBtn && !syncIndexBtn.dataset.bound) {
    syncIndexBtn.dataset.bound = '1';
    syncIndexBtn.addEventListener('click', () => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-ai', 'mgmt-pane-ai-index');
      }
    });
  }

  // Quick Sync Active Shares button in ribbon (#btn-ai-quick-sync) & Indexer Sync Watched button (#btn-ai-sync-watched)
  document.querySelectorAll('#btn-ai-quick-sync, #btn-ai-sync-watched').forEach((syncBtn) => {
    if (syncBtn.dataset.bound) return;
    syncBtn.dataset.bound = '1';
    syncBtn.addEventListener('click', async () => {
      const respectCb = document.getElementById('ai-index-respect-standby') || document.getElementById('ai-respect-standby-cb');
      const respect = respectCb ? Boolean(respectCb.checked) : true;
      syncBtn.disabled = true;
      const origHtml = syncBtn.innerHTML;
      syncBtn.innerHTML = '<span aria-hidden="true">⏳</span> <span>Syncing Shares...</span>';
      try {
        await syncAiWatchedFolders(respect, true);
      } finally {
        syncBtn.disabled = false;
        syncBtn.innerHTML = origHtml;
      }
    });
  });

  // Pause / Resume / Stop Sync buttons (both ribbon and Indexer pane)
  document.querySelectorAll('#btn-ai-sync-pause, #btn-ai-index-pause').forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => controlAiSync('pause'));
  });
  document.querySelectorAll('#btn-ai-sync-resume, #btn-ai-index-resume').forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => controlAiSync('resume'));
  });
  document.querySelectorAll('#btn-ai-sync-stop, #btn-ai-index-stop').forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => controlAiSync('stop'));
  });
  document.querySelectorAll('#btn-ai-flush-index, #btn-ai-flush-index-link').forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => flushAiIndex());
  });

  // Watched Folders Multi-Select Dropdown (#btn-ai-watched-folders-dropdown)
  const watchedDropdownBtn = document.getElementById('btn-ai-watched-folders-dropdown');
  if (watchedDropdownBtn && !watchedDropdownBtn.dataset.bound) {
    watchedDropdownBtn.dataset.bound = '1';
    watchedDropdownBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      setAiWatchedFoldersDropdownOpen();
    });
  }
  if (!document.body.dataset.aiWatchedDropdownOutsideBound) {
    document.body.dataset.aiWatchedDropdownOutsideBound = '1';
    document.addEventListener('click', (e) => {
      const container = document.getElementById('ai-watched-folders-dropdown-container');
      const menu = document.getElementById('ai-watched-folders-dropdown-menu');
      if (menu && menu.style.display !== 'none' && container && !container.contains(e.target)) {
        setAiWatchedFoldersDropdownOpen(false);
      }
    });
  }

  // Browse Folder button (#btn-ai-browse-folder)
  const browseBtn = document.getElementById('btn-ai-browse-folder');
  if (browseBtn && !browseBtn.dataset.bound) {
    browseBtn.dataset.bound = '1';
    browseBtn.addEventListener('click', () => {
      const pathIn = document.getElementById('ai-index-target-path') || document.getElementById('ai-index-path-input');
      const startPath = (pathIn && pathIn.value.trim()) ? pathIn.value.trim() : '/mnt/user/';
      if (typeof window.openFolderBrowser === 'function') {
        window.openFolderBrowser(startPath, (selectedPath) => {
          const clean = String(selectedPath || '').replace(/\/+$/, '') || '/mnt/user';
          if (pathIn) pathIn.value = clean;
          addAiWatchedFolder(clean);
        });
      }
    });
  }

  // Add Folder to Watched List (#btn-ai-add-watched-folder)
  const addFolderBtn = document.getElementById('btn-ai-add-watched-folder');
  if (addFolderBtn && !addFolderBtn.dataset.bound) {
    addFolderBtn.dataset.bound = '1';
    addFolderBtn.addEventListener('click', () => {
      const pathIn = document.getElementById('ai-index-target-path') || document.getElementById('ai-index-path-input');
      if (pathIn && pathIn.value.trim()) {
        addAiWatchedFolder(pathIn.value.trim());
      }
    });
  }

  // Unified Omni-Search & RAG Ask handlers
  const askInput = document.getElementById('ai-rag-query-input');
  const askBtn = document.getElementById('btn-ai-rag-ask');
  const executeUnifiedOmniSearch = (rawQuery) => {
    const q = String(rawQuery || '').trim();
    const visInputEl = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
    if (visInputEl) visInputEl.value = q;
    runAiRagAsk(q, { unifiedMode: true });
    if (document.getElementById('ai-visual-results-grid')) {
      runAiVisualSearch(q);
    }
  };
  if (askBtn && !askBtn.dataset.bound) {
    askBtn.dataset.bound = '1';
    askBtn.addEventListener('click', () => {
      if (askInput) executeUnifiedOmniSearch(askInput.value);
    });
  }
  if (askInput && !askInput.dataset.bound) {
    askInput.dataset.bound = '1';
    askInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        executeUnifiedOmniSearch(askInput.value);
      }
    });
  }

  // Starter / Quick Prompt Chips (.ai-starter-chip and .ai-quick-prompt-chip)
  document.querySelectorAll('.ai-starter-chip, .ai-quick-prompt-chip').forEach((chip) => {
    if (chip.dataset.bound) return;
    chip.dataset.bound = '1';
    chip.addEventListener('click', () => {
      const q = (chip.dataset.query || '').trim();
      const isVisual = chip.dataset.switchVisual === '1' || chip.dataset.mode === 'visual';
      const currentAskIn = document.getElementById('ai-rag-query-input');
      if (currentAskIn) currentAskIn.value = q;
      const visIn = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
      if (visIn) visIn.value = q;
      if (isVisual) {
        const visualTab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-ai-visual"]');
        if (visualTab) visualTab.click();
        const answerCard = document.getElementById('ai-rag-answer-card');
        if (answerCard) answerCard.style.display = 'none';
        runAiVisualSearch(q);
      } else {
        executeUnifiedOmniSearch(q);
      }
    });
  });

  // Visual Search Input, Search Button & Clear Button
  const visInput = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
  const visBtn = document.getElementById('btn-ai-visual-search');
  if (visBtn && !visBtn.dataset.bound) {
    visBtn.dataset.bound = '1';
    visBtn.addEventListener('click', () => {
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  }
  if (visInput && !visInput.dataset.bound) {
    visInput.dataset.bound = '1';
    visInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        runAiVisualSearch(visInput.value);
      }
    });
  }

  // File Type Filter Chips (#ai-search-filetype-bar .ai-filetype-chip)
  document.querySelectorAll('#ai-search-filetype-bar .ai-filetype-chip').forEach((chip) => {
    if (chip.dataset.bound) return;
    chip.dataset.bound = '1';
    chip.addEventListener('click', () => {
      _aiSelectedFileType = chip.dataset.filetype || 'all';
      document.querySelectorAll('#ai-search-filetype-bar .ai-filetype-chip').forEach((c) => {
        const isAct = c === chip;
        c.classList.toggle('active', isAct);
        c.style.borderColor = isAct ? '#38bdf8' : '';
      });
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  });

  // Result Matching Mode Tabs (Semantic / Keyword / Audio)
  document.querySelectorAll('#ai-search-match-tabs .ai-match-tab').forEach((tabBtn) => {
    if (tabBtn.dataset.bound) return;
    tabBtn.dataset.bound = '1';
    tabBtn.addEventListener('click', () => {
      _aiSelectedMatchTab = tabBtn.dataset.matchTab || 'semantic';
      document.querySelectorAll('#ai-search-match-tabs .ai-match-tab').forEach((b) => {
        const isAct = b === tabBtn;
        b.classList.toggle('active', isAct);
        b.style.background = isAct ? 'rgba(14,165,233,0.28)' : 'transparent';
        b.style.color = isAct ? '#fff' : '#94a3b8';
      });
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  });

  // Sort Selector (#ai-search-sort-select)
  const sortSelect = document.getElementById('ai-search-sort-select');
  if (sortSelect && !sortSelect.dataset.bound) {
    sortSelect.dataset.bound = '1';
    sortSelect.addEventListener('change', () => {
      _aiSelectedSortBy = sortSelect.value || 'relevance';
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  }

  const visClearBtn = document.getElementById('btn-ai-visual-clear');
  if (visClearBtn && !visClearBtn.dataset.bound) {
    visClearBtn.dataset.bound = '1';
    visClearBtn.addEventListener('click', () => {
      _aiSelectedColor = '';
      _aiSelectedScene = '';
      _aiSelectedFileType = 'all';
      _aiSelectedMatchTab = 'semantic';
      _aiSelectedSortBy = 'relevance';
      const activeVisInput = document.getElementById('ai-visual-search-input') || document.getElementById('ai-visual-query-input');
      if (activeVisInput) activeVisInput.value = '';
      const activeAskInput = document.getElementById('ai-rag-query-input');
      if (activeAskInput) activeAskInput.value = '';
      const answerCard = document.getElementById('ai-rag-answer-card');
      if (answerCard) answerCard.style.display = 'none';
      document.querySelectorAll('#ai-color-filter-bar .ai-color-chip, #ai-color-swatch-bar .ai-color-swatch').forEach((s) => {
        s.classList.remove('active');
        s.style.border = '';
        s.style.boxShadow = '';
      });
      document.querySelectorAll('#ai-scene-filter-bar .ai-scene-chip, #ai-scene-pill-bar .ai-scene-pill').forEach((p) => {
        p.classList.remove('active');
        p.style.background = '';
        p.style.borderColor = '';
        p.style.color = '';
      });
      document.querySelectorAll('#ai-search-filetype-bar .ai-filetype-chip').forEach((c) => {
        const isAll = c.dataset.filetype === 'all';
        c.classList.toggle('active', isAll);
        c.style.borderColor = isAll ? '#38bdf8' : '';
      });
      _updateAiVisualFilterBadge();
      const banner = document.getElementById('ai-visual-intent-banner');
      if (banner) banner.style.display = 'none';
      const inspector = document.getElementById('ai-preview-inspector-pane');
      const splitLayout = document.getElementById('ai-search-split-layout');
      if (inspector) inspector.style.display = 'none';
      if (splitLayout) splitLayout.style.gridTemplateColumns = 'minmax(0, 1fr)';
      runAiVisualSearch('');
    });
  }

  // 12-Color Swatch Chips (#ai-color-filter-bar .ai-color-chip and #ai-color-swatch-bar .ai-color-swatch)
  document.querySelectorAll('#ai-color-filter-bar .ai-color-chip, #ai-color-swatch-bar .ai-color-swatch').forEach((swatch) => {
    if (swatch.dataset.bound) return;
    swatch.dataset.bound = '1';
    swatch.addEventListener('click', () => {
      const clickedColor = swatch.dataset.color || '';
      _aiSelectedColor = (_aiSelectedColor === clickedColor && clickedColor !== '') ? '' : clickedColor;
      document.querySelectorAll('#ai-color-filter-bar .ai-color-chip, #ai-color-swatch-bar .ai-color-swatch').forEach((s) => {
        const active = (s.dataset.color || '') === _aiSelectedColor && (_aiSelectedColor !== '' || s === swatch);
        s.classList.toggle('active', active);
        s.style.border = active ? '2px solid #00f0ff' : '';
        s.style.boxShadow = active ? '0 0 8px rgba(0,240,255,0.35)' : '';
      });
      _updateAiVisualFilterBadge();
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  });

  // Scene & Object Filter Pills (#ai-scene-filter-bar .ai-scene-chip and #ai-scene-pill-bar .ai-scene-pill)
  document.querySelectorAll('#ai-scene-filter-bar .ai-scene-chip, #ai-scene-pill-bar .ai-scene-pill').forEach((pill) => {
    if (pill.dataset.bound) return;
    pill.dataset.bound = '1';
    pill.addEventListener('click', () => {
      const clickedScene = pill.dataset.scene || '';
      _aiSelectedScene = (_aiSelectedScene === clickedScene && clickedScene !== '') ? '' : clickedScene;
      document.querySelectorAll('#ai-scene-filter-bar .ai-scene-chip, #ai-scene-pill-bar .ai-scene-pill').forEach((p) => {
        const active = (p.dataset.scene || '') === _aiSelectedScene && (_aiSelectedScene !== '' || p === pill);
        p.classList.toggle('active', active);
        p.style.background = active ? 'rgba(56,189,248,0.22)' : '';
        p.style.borderColor = active ? 'rgba(56,189,248,0.55)' : '';
        p.style.color = active ? '#38bdf8' : '';
      });
      _updateAiVisualFilterBadge();
      runAiVisualSearch(_getActiveAiSearchQuery());
    });
  });

  // Index Path Execution (#btn-ai-run-index and #btn-ai-run-index-path)
  document.querySelectorAll('#btn-ai-run-index, #btn-ai-run-index-path').forEach((runIdxBtn) => {
    if (runIdxBtn.dataset.bound) return;
    runIdxBtn.dataset.bound = '1';
    runIdxBtn.addEventListener('click', () => {
      const pathIn = document.getElementById('ai-index-target-path') || document.getElementById('ai-index-path-input');
      const respectCb = document.getElementById('ai-index-respect-standby') || document.getElementById('ai-respect-standby-cb');
      const explicitPath = (pathIn && pathIn.value && pathIn.value.trim()) ? pathIn.value.trim() : null;
      runAiPathIndex(
        explicitPath,
        respectCb ? Boolean(respectCb.checked) : true
      );
    });
  });

  // Merged Standby-Safe Auto-Learn checkbox (#ai-index-respect-standby)
  const respectStandbyCb = document.getElementById('ai-index-respect-standby');
  if (respectStandbyCb && !respectStandbyCb.dataset.bound) {
    respectStandbyCb.dataset.bound = '1';
    respectStandbyCb.addEventListener('change', async () => {
      const enabled = Boolean(respectStandbyCb.checked);
      await updateAiServiceConfig({
        respect_standby: enabled,
        auto_learn_on_spinup: enabled,
      });
      showToast(
        enabled
          ? t('ai.auto_learn_spinup_on', '⚡ Standby-Safe Auto-Learn enabled — sleeping drives are protected and automatically sync when they spin up.')
          : t('ai.auto_learn_spinup_off', 'Standby-Safe Auto-Learn disabled.'),
        'info'
      );
    });
  }
  const autoLearnSpinupCb = document.getElementById('ai-auto-learn-spinup');
  if (autoLearnSpinupCb && !autoLearnSpinupCb.dataset.bound) {
    autoLearnSpinupCb.dataset.bound = '1';
    autoLearnSpinupCb.addEventListener('change', async () => {
      const auto_learn_on_spinup = Boolean(autoLearnSpinupCb.checked);
      await updateAiServiceConfig({
        respect_standby: auto_learn_on_spinup,
        auto_learn_on_spinup,
      });
    });
  }

  // Active LLM Pill click -> jumps to AI Chatbot & NAS Copilot tab
  const activeLlmPill = document.getElementById('ai-active-llm-pill');
  if (activeLlmPill && !activeLlmPill.dataset.bound) {
    activeLlmPill.dataset.bound = '1';
    activeLlmPill.style.cursor = 'pointer';
    activeLlmPill.addEventListener('click', () => {
      const chatTab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-ai-chat"]');
      if (chatTab) chatTab.click();
    });
  }

  // AI Chatbot & NAS Copilot Controls (#mgmt-pane-ai-chat)
  const chatSendBtn = document.getElementById('btn-ai-chat-send');
  const chatInput = document.getElementById('ai-chat-input');
  const chatClearBtn = document.getElementById('btn-ai-chat-clear');
  const chatStopBtn = document.getElementById('btn-ai-chat-stop');
  if (chatStopBtn && !chatStopBtn.dataset.bound) {
    chatStopBtn.dataset.bound = '1';
    chatStopBtn.addEventListener('click', () => stopAiChatGeneration());
  }
  if (chatSendBtn && !chatSendBtn.dataset.bound) {
    chatSendBtn.dataset.bound = '1';
    chatSendBtn.addEventListener('click', () => {
      sendAiChatMessage(chatInput ? chatInput.value : '');
    });
  }
  if (chatInput && !chatInput.dataset.bound) {
    chatInput.dataset.bound = '1';
    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendAiChatMessage(chatInput.value);
      }
    });
  }
    initAiConversationControls();
  if (chatClearBtn && !chatClearBtn.dataset.bound) {
    chatClearBtn.dataset.bound = '1';
    chatClearBtn.addEventListener('click', () => {
      clearAiChatHistory();
    });
  }
  document.querySelectorAll('.ai-chat-starter-chip').forEach((chip) => {
    if (chip.dataset.bound) return;
    chip.dataset.bound = '1';
    chip.addEventListener('click', () => {
      const prompt = (chip.dataset.chatPrompt || '').trim();
      if (prompt) {
        if (chatInput) chatInput.value = prompt;
        sendAiChatMessage(prompt);
      }
    });
  });

  // Initial background status fetch to populate topbar NPU/GPU pill and 3-tier hardware cards
  setTimeout(() => {
    fetchAndRenderAiStatus().catch(() => {});
  }, 300);
}

export async function fetchAndRenderAiStatus() {
  try {
    const res = await api.get('/api/media/status');
    if (!res) return null;

    const hw = res.hardware || res.acceleration || {};
    const stats = res.index_stats || {};
    const cats = res.categories || {};
    const cfg = res.config || {};
    const tierNum = Number(hw.tier_number || hw.active_tier || (hw.has_npu ? 1 : (hw.has_igpu || hw.has_cuda || hw.has_rocm ? 2 : 3)));
    const tierBadge = tierNum === 1 ? 'NPU TIER 1' : tierNum === 2 ? 'GPU TIER 2' : 'CPU TIER 3';
    const tierShort = tierNum === 1 ? 'NPU' : tierNum === 2 ? 'GPU' : 'CPU';
    const hwName = hw.name || hw.device_label || (tierNum === 1 ? 'Intel AI Boost NPU (/dev/accel/accel0)' : tierBadge);
    const totalFiles = stats.total_files ?? res.indexed_count ?? 0;
    const totalVideos = stats.total_videos ?? cats.videos ?? 0;
    const totalDocs = stats.total_docs ?? stats.total_documents ?? cats.documents ?? 0;
    const totalRecipes = stats.total_recipes ?? cats.recipes ?? 0;
    const totalPhotos = stats.total_photos ?? cats.photos ?? 0;
    const totalChunks = stats.total_chunks ?? cats.chunks ?? 0;

    // Sync ZettAI Master Switch & Learning Scope/Schedule inputs
    const masterToggle = document.getElementById('ai-master-enable-toggle');
    if (masterToggle && res.enabled !== undefined) {
      masterToggle.checked = Boolean(res.enabled);
    }
    const scopeModeSelect = document.getElementById('ai-learning-scope-mode');
    if (scopeModeSelect && (res.scope_mode || cfg.scope_mode)) {
      scopeModeSelect.value = res.scope_mode || cfg.scope_mode || 'include';
    }
    const schedToggle = document.getElementById('ai-schedule-enabled-toggle');
    if (schedToggle && cfg.schedule_enabled !== undefined) {
      schedToggle.checked = Boolean(cfg.schedule_enabled);
    }
    const schedStart = document.getElementById('ai-schedule-start-input');
    if (schedStart && cfg.schedule_start) schedStart.value = cfg.schedule_start;
    const schedEnd = document.getElementById('ai-schedule-end-input');
    if (schedEnd && cfg.schedule_end) schedEnd.value = cfg.schedule_end;
    if (typeof window !== 'undefined' && window.initGlassTimePickers) {
      window.initGlassTimePickers(document.getElementById('mgmt-sec-ai') || document);
    }
    const respectCbEl = document.getElementById('ai-index-respect-standby');
    if (respectCbEl && (cfg.respect_standby !== undefined || res.standby_guard?.respect_standby !== undefined)) {
      respectCbEl.checked = Boolean(cfg.respect_standby ?? res.standby_guard?.respect_standby ?? true);
    }
    const autoSpinupCbEl = document.getElementById('ai-auto-learn-spinup');
    if (autoSpinupCbEl && (cfg.auto_learn_on_spinup !== undefined || res.standby_guard?.auto_learn_on_spinup !== undefined)) {
      autoSpinupCbEl.checked = Boolean(cfg.auto_learn_on_spinup ?? res.standby_guard?.auto_learn_on_spinup ?? true);
    }

    const retentionSel = document.getElementById('ai-conversation-retention-select');
    if (retentionSel) {
      retentionSel.value = String(cfg.conversation_retention_days ?? 0);
      if (!retentionSel.dataset.bound) {
        retentionSel.dataset.bound = '1';
        retentionSel.addEventListener('change', async (e) => {
          try {
            await api.post('/api/ai/config', { conversation_retention_days: parseInt(e.target.value, 10) || 0 });
            showToast(t('ai.retention_saved', 'Chat retention saved'), 'success');
          } catch (err) {
            showToast(t('toast.ai_retention_failed', 'Could not save chat retention: {error}', { error: err.message }), 'error');
          }
        });
      }
    }

    // Optional reranker (AI-13)
    const rerankForm = document.getElementById('ai-rerank-form');
    if (rerankForm) {
      const ep = document.getElementById('ai-rerank-endpoint');
      const md = document.getElementById('ai-rerank-model');
      if (ep) ep.value = cfg.rerank_endpoint || '';
      if (md) md.value = cfg.rerank_model || '';
      if (!rerankForm.dataset.bound) {
        rerankForm.dataset.bound = '1';
        rerankForm.addEventListener('submit', async (e) => {
          e.preventDefault();
          try {
            await api.post('/api/ai/config', { rerank_endpoint: ep.value.trim(), rerank_model: md.value.trim() });
            showToast(t('ai.rerank_saved', 'Reranker saved'), 'success');
          } catch (err) {
            showToast(t('sso.save_failed', 'Could not save: {error}', { error: err.message }), 'error');
          }
        });
      }
    }

    // Photo captions (AI-14)
    const visionSel = document.getElementById('ai-vision-captions-select');
    if (visionSel) {
      visionSel.value = cfg.vision_captions === 'off' ? 'off' : 'auto';
      if (!visionSel.dataset.bound) {
        visionSel.dataset.bound = '1';
        visionSel.addEventListener('change', async (e) => {
          try {
            await api.post('/api/ai/config', { vision_captions: e.target.value });
            showToast(t('ai.vision_saved', 'Photo captioning setting saved'), 'success');
            refreshVisionStatus();
          } catch (err) {
            showToast(t('toast.ai_vision_failed', 'Could not save the photo captioning setting: {error}', { error: err.message }), 'error');
          }
        });
      }
      refreshVisionStatus();
    }

    // Hydrate Embedding Model & MRL Dimension selectors
    const embModelSelect = document.getElementById('ai-embedding-model-select');
    if (embModelSelect && (cfg.embedding_model || res.embedding_model)) {
      const embVal = cfg.embedding_model || res.embedding_model || 'embeddinggemma';
      // older installs saved the name "google/embeddinggemma-2" for the same model
      embModelSelect.value = /embeddinggemma/i.test(embVal) ? 'embeddinggemma' : embVal;
    }
    const mrlDimSelect = document.getElementById('ai-mrl-dimension-select');
    if (mrlDimSelect && (cfg.embedding_dim !== undefined || res.embedding_dim !== undefined)) {
      mrlDimSelect.value = String(cfg.embedding_dim ?? res.embedding_dim ?? 768);
    }

    if (embModelSelect && !embModelSelect.dataset.bound) {
      embModelSelect.dataset.bound = '1';
      embModelSelect.addEventListener('change', async (e) => {
        const val = e.target.value;
        try {
          await api.post('/api/ai/config', { embedding_model: val });
          showToast(t('ai.embedding_model_saved', 'Embedding model updated'), 'success');
        } catch (err) {
          showToast(t('toast.failed_update_embedding_model', 'Failed to update embedding model: {error}', { error: err.message }), 'error');
        }
      });
    }

    if (mrlDimSelect && !mrlDimSelect.dataset.bound) {
      mrlDimSelect.dataset.bound = '1';
      mrlDimSelect.addEventListener('change', async (e) => {
        const val = parseInt(e.target.value, 10);
        try {
          await api.post('/api/ai/config', { embedding_dim: val });
          showToast(t('ai.mrl_dim_saved', 'Vector size updated'), 'success');
        } catch (err) {
          showToast(t('toast.failed_update_vector_size', 'Failed to update vector size: {error}', { error: err.message }), 'error');
        }
      });
    }

    const btnBenchmark = document.getElementById('btn-ai-run-benchmark');
    if (btnBenchmark && !btnBenchmark.dataset.bound) {
      btnBenchmark.dataset.bound = '1';
      btnBenchmark.addEventListener('click', async () => {
        btnBenchmark.disabled = true;
        const origHtml = btnBenchmark.innerHTML;
        btnBenchmark.innerHTML = `<span aria-hidden="true">⏳</span> <span>${t('ai.benchmark_running') || 'Benchmarking Hardware...'}</span>`;
        try {
          const bRes = await api.post('/api/ai/benchmark');
          if (bRes && bRes.status === 'ok') {
            const card = document.getElementById('ai-benchmark-results-card');
            if (card) card.style.display = 'grid';
            const latEl = document.getElementById('bm-latency');
            if (latEl) latEl.textContent = `${bRes.latency_ms} ms`;
            const tpEl = document.getElementById('bm-throughput');
            if (tpEl) tpEl.textContent = `${bRes.throughput_chunks_sec} chunks/s`;
            const tokEl = document.getElementById('bm-tokens');
            if (tokEl) tokEl.textContent = `${bRes.tokens_per_sec} tok/s`;
            const accelEl = document.getElementById('bm-accel');
            if (accelEl) accelEl.textContent = bRes.accelerator || 'CPU';
            showToast(t('toast.ai_benchmark_completed_successfully', 'AI benchmark completed successfully'), 'success');
          }
        } catch (err) {
          showToast(t('toast.benchmark_failed', 'Benchmark failed: {error}', { error: err.message }), 'error');
        } finally {
          btnBenchmark.disabled = false;
          btnBenchmark.innerHTML = origHtml;
        }
      });
    }

    // Bind In-Place Re-index buttons
    const bindReindexBtn = (btnId) => {
      const b = document.getElementById(btnId);
      if (b && !b.dataset.bound) {
        b.dataset.bound = '1';
        b.addEventListener('click', async () => {
          b.disabled = true;
          try {
            await triggerInPlaceReindex();
          } finally {
            setTimeout(() => { b.disabled = false; }, 2000);
          }
        });
      }
    };
    bindReindexBtn('btn-ai-trigger-reindex');
    bindReindexBtn('btn-ai-in-place-reindex');

    // Check if in-place re-index is actively running
    const reindexStatus = res && res.reindex_status;
    if (reindexStatus && reindexStatus.status === 'running') {
      try {
        updateAiReindexProgress(reindexStatus);
        _pollReindexProgress();
      } catch (_) {}
    }

    // Render NPU & GPU LLM Recommendations
    const activeModelId = res.active_model || cfg.llm_model || _aiLastActiveModel || '';
    _aiLastActiveModel = activeModelId;
    const activeLlmLabel = document.getElementById('ai-active-llm-label');
    const activeLlmPill = document.getElementById('ai-active-llm-pill');
    if (activeLlmLabel) {
      activeLlmLabel.textContent = activeModelId || '—';
    }
    if (activeLlmPill) {
      activeLlmPill.title = `Active Local LLM: ${activeModelId} on ${hwName} — Leveraged by RAG Synthesis & NAS Copilot Chatbot`;
    }
    const chatModelBadge = document.getElementById('ai-chat-active-model-badge');
    if (chatModelBadge) {
      chatModelBadge.textContent = activeModelId ? `🤖 ${activeModelId} (${tierShort} Tier ${tierNum})` : '🤖 —';
    }
    if (res.llm_recommendations) {
      renderAiLlmRecommendations(res.llm_recommendations, activeModelId);
    }

    // Render Learning Results if present
    if (res.learning_results) {
      renderAiLearningResultsData(res.learning_results);
    }

    // Topbar Pill (#topbar-ai-accel-text in index.html & #topbar-ai-accel-label in unit tests)
    const topText = document.getElementById('topbar-ai-accel-text');
    const topLabel = document.getElementById('topbar-ai-accel-label');
    const topDot = document.getElementById('topbar-ai-accel-dot');
    const topPill = document.getElementById('topbar-ai-accel-pill');
    const isReindexing = Boolean(reindexStatus && reindexStatus.status === 'running');
    if (topText && !isReindexing) topText.textContent = cfg.respect_standby === false ? tierShort : `${tierShort} • Standby Safe`;
    if (topLabel) topLabel.textContent = `AI: ${tierShort}`;
    if (topDot && !isReindexing) {
      topDot.style.background = tierNum === 1 ? '#3bf58b' : tierNum === 2 ? '#38bdf8' : '#a78bfa';
      topDot.style.boxShadow = tierNum === 1 ? '0 0 6px #3bf58b' : tierNum === 2 ? '0 0 6px #38bdf8' : '0 0 6px #a78bfa';
    }
    if (topPill) {
      topPill.title = `ZettAI Active Accelerator: ${hwName} (NPU → GPU → CPU Priority) • ${totalFiles} Indexed Files`;
    }

    // Sidebar & Hub Badges
    const sideBadge = document.getElementById('mgmt-sidebar-ai-badge');
    if (sideBadge && !isReindexing) sideBadge.textContent = tierShort;
    const hubPill = document.getElementById('mgmt-hub-ai-pill');
    if (hubPill) {
      hubPill.textContent = `${tierBadge} • ${totalFiles} Files`;
    }

    // Section Telemetry Ribbon (#ai-accel-active-label in index.html & #ai-active-tier-pill in tests)
    const activeLabel = document.getElementById('ai-accel-active-label');
    const accelChainPill = document.getElementById('ai-accel-chain-pill');
    if (activeLabel) {
      const compactHwName = String(hwName).replace(/\s*\([^)]*\)/g, '').trim() || tierShort;
      activeLabel.textContent = `Tier ${tierNum}: ${compactHwName}`;
      if (accelChainPill) {
        accelChainPill.title = `Tier ${tierNum}: ${tierShort} Active (${hwName})`;
      }
    }
    const tierPill = document.getElementById('ai-active-tier-pill');
    if (tierPill) {
      tierPill.textContent = `⚡ ${tierBadge}: ${hwName}`;
    }
    const devLabel = document.getElementById('ai-accel-device-label');
    if (devLabel) {
      devLabel.textContent = `${hwName} (${hw.execution_provider || 'OpenVINOExecutionProvider'})`;
    }

    // Stats counters (both index.html and test IDs)
    const statFilesPill = document.getElementById('ai-stat-total-files');
    if (statFilesPill) statFilesPill.textContent = String(totalFiles);
    const statVideos = document.getElementById('ai-stat-total-videos');
    if (statVideos) statVideos.textContent = String(totalVideos);
    const statDocs = document.getElementById('ai-stat-total-docs');
    if (statDocs) statDocs.textContent = String(totalDocs);
    const statRecipes = document.getElementById('ai-stat-total-recipes');
    if (statRecipes) statRecipes.textContent = String(totalRecipes);
    const statRecipesSeg = document.getElementById('ai-stat-recipes-segment');
    if (statRecipesSeg) {
      statRecipesSeg.style.display = totalRecipes > 0 ? 'inline' : 'none';
    }
    const statTotalPhotos = document.getElementById('ai-stat-total-photos');
    if (statTotalPhotos) statTotalPhotos.textContent = String(totalPhotos);

    const statFiles = document.getElementById('ai-stat-files');
    if (statFiles) statFiles.textContent = String(totalFiles);
    const statChunks = document.getElementById('ai-stat-chunks');
    if (statChunks) statChunks.textContent = String(totalChunks);
    const statPhotos = document.getElementById('ai-stat-photos');
    if (statPhotos) statPhotos.textContent = String(totalPhotos);

    // 3-Tier Cards in Indexer Tab (#ai-hw-tier1..3-status in index.html & #ai-tier1..3-status in tests)
    const t1List = [document.getElementById('ai-hw-tier1-status'), document.getElementById('ai-tier1-status')].filter(Boolean);
    const t2List = [document.getElementById('ai-hw-tier2-status'), document.getElementById('ai-tier2-status')].filter(Boolean);
    const t3List = [document.getElementById('ai-hw-tier3-status'), document.getElementById('ai-tier3-status')].filter(Boolean);

    t1List.forEach((t1) => {
      t1.textContent = tierNum === 1
        ? `✓ ACTIVE: ${hwName}`
        : 'Standby / Not Detected — Automatically promoted when /dev/accel/accel0, /dev/rknpu, or /dev/hailo0 is present.';
      t1.style.color = tierNum === 1 ? '#3bf58b' : 'var(--muted)';
    });

    const secGpuLabel = hw.secondary_gpu || (hw.has_igpu ? 'Intel Arc / QuickSync iGPU (/dev/dri/renderD128)' : '');
    t2List.forEach((t2) => {
      t2.textContent = tierNum === 2
        ? `✓ ACTIVE: ${hwName}`
        : tierNum === 1
          ? `✓ Ready as Secondary Fallback${secGpuLabel ? `: ${secGpuLabel}` : ' (Tier 1 NPU currently active)'}`
          : 'Standby / Not Detected — Automatically promoted when /dev/nvidia0 or /dev/dri/renderD128 is present.';
      t2.style.color = (tierNum === 2 || (tierNum === 1 && secGpuLabel)) ? '#38bdf8' : 'var(--muted)';
    });

    t3List.forEach((t3) => {
      const dimFallback = stats.actual_embedding_dim || stats.embedding_dim || 768;
      t3.textContent = tierNum === 3
        ? `✓ ACTIVE: ${hwName} (${hw.execution_provider || 'CPUExecutionProvider'})`
        : `✓ Ready as Universal Fallback (${dimFallback}-d EmbeddingGemma 2 MRL Engine)`;
      t3.style.color = tierNum === 3 ? '#c4b5fd' : 'var(--ok2, #25c2a0)';
    });

    const dbSummary = document.getElementById('ai-index-db-summary');
    if (dbSummary) {
      const sizeKb = stats.db_size_bytes ? (stats.db_size_bytes / 1024).toFixed(1) : '0.0';
      const defItems = res.standby_guard?.deferred_queue || res.sync_progress?.deferred_queue || [];
      const defCount = stats.deferred_queue_count ?? defItems.length ?? 0;
      const defDetail = defItems.length > 0
        ? ` <span style="color:var(--lt-t-fbbf24ff, #fbbf24);">(${defItems.map((d) => `${escapeHtml(d.path)}${d.backing_dev ? ` [${escapeHtml(d.backing_dev)}]` : ''}`).join(', ')} — ⚡ auto-learns on spin-up)</span>`
        : (defCount > 0 ? ' <span style="color:var(--lt-t-6ee7b7ff, #6ee7b7);">(⚡ auto-learns on spin-up)</span>' : '');
      const dimLabel = stats.actual_embedding_dim || stats.embedding_dim || 768;
      const modelRaw = stats.actual_embedding_model || stats.embedding_model || 'EmbeddingGemma 2';
      const modelDisplayName = modelRaw.includes('embeddinggemma') ? 'EmbeddingGemma 2 MRL' : modelRaw;
      const totalVideos = stats.total_videos || 0;
      const videoDetail = totalVideos > 0 ? `, ${totalVideos} videos` : '';
      dbSummary.innerHTML = `
        <div>• <strong>Indexed Files:</strong> ${totalFiles} (${totalDocs} documents/recipes, ${totalPhotos} photos${videoDetail})</div>
        <div>• <strong>Semantic Chunks &amp; Vectors:</strong> ${totalChunks} (${dimLabel}-d ${escapeHtml(modelDisplayName)} + FTS5 BM25)</div>
        <div>• <strong>Deferred Standby Queue:</strong> ${defCount} path(s) waiting for drive wake${defDetail}</div>
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
          <span>• <strong>NVMe Index Footprint:</strong> ${sizeKb} KB (<code>${escapeHtml(stats.db_path || '/app/data/rag_index.db')}</code>)</span>
          ${totalFiles > 0 || totalChunks > 0 ? `<button type="button" id="btn-ai-flush-index-link" class="btn-pill-toggle is-danger is-small" title="${t('ui.flush_existing_rag_index_vector', 'Flush existing RAG index, vector embeddings, and search catalog to start fresh')}"><span aria-hidden="true">🗑️</span> <span>Flush &amp; Start Fresh</span></button>` : ''}
        </div>
      `;
      const flushLink = dbSummary.querySelector('#btn-ai-flush-index-link');
      if (flushLink) {
        flushLink.addEventListener('click', () => flushAiIndex());
      }
    }

    // Update Sync Progress & Transport Controls
    const syncProg = res.sync_progress || stats.sync_progress || {
      state: res.sync_state || (res.is_paused ? 'paused' : (res.is_scanning ? 'running' : 'idle')),
      is_scanning: Boolean(res.is_scanning),
      is_paused: Boolean(res.is_paused),
      enabled: res.enabled,
    };
    updateAiSyncProgressUi(syncProg, res.standby_guard || {}, res.zettai_status || '');

    // Update Watched Folders & Discovered Shares
    const watchedList = res.watched_paths || res.config?.watched_paths || stats.watched_paths || ['/mnt/user'];
    const availFolders = res.available_folders || [];
    renderAiWatchedFoldersAndShares(watchedList, availFolders);

    return res;
  } catch (err) {
    return null;
  }
}

function renderStructuredCardHtml(card) {
  if (!card) return '';
  const cType = card.type || card.card_type || '';
  if (cType === 'recipe') {
    const ings = (card.ingredients || []).slice(0, 12).map((i) => `<li>${escapeHtml(i)}</li>`).join('');
    const steps = (card.steps || card.steps_summary || []).slice(0, 6).map((s) => `<li>${escapeHtml(s)}</li>`).join('');
    return `
      <div class="ai-structured-recipe-card" style="background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.28); border-radius: 10px; padding: 14px; display: flex; flex-direction: column; gap: 10px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 18px;">🍳</span>
            <span style="font-weight: 800; font-size: 13.5px; color: var(--lt-t-ffffffff, #fff);">${escapeHtml(card.title || 'Structured Recipe Card')}</span>
          </div>
          <div style="display: flex; gap: 6px; font-size: 11px;">
            ${card.prep_time ? `<span style="padding: 2px 8px; border-radius: 999px; background: var(--lt-b-0000004c, rgba(0,0,0,0.3)); color: var(--lt-t-6ee7b7ff, #6ee7b7);">⏱ Prep: ${escapeHtml(card.prep_time)}</span>` : ''}
            ${card.cook_time ? `<span style="padding: 2px 8px; border-radius: 999px; background: var(--lt-b-0000004c, rgba(0,0,0,0.3)); color: var(--lt-t-fde68aff, #fde68a);">🔥 Cook: ${escapeHtml(card.cook_time)}</span>` : ''}
            ${card.servings ? `<span style="padding: 2px 8px; border-radius: 999px; background: var(--lt-b-0000004c, rgba(0,0,0,0.3)); color: var(--lt-t-bae6fdff, #bae6fd);">🍽 Serves: ${escapeHtml(card.servings)}</span>` : ''}
          </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; font-size: 11.5px;">
          ${ings ? `<div><div style="font-weight: 700; color: var(--lt-t-6ee7b7ff, #6ee7b7); margin-bottom: 4px; text-transform: uppercase; font-size: 11px;">Ingredients</div><ul style="margin: 0; padding-left: 16px; color: var(--lt-t-e2e8f0ff, #e2e8f0); line-height: 1.5;">${ings}</ul></div>` : ''}
          ${steps ? `<div><div style="font-weight: 700; color: var(--lt-t-93c5fdff, #93c5fd); margin-bottom: 4px; text-transform: uppercase; font-size: 11px;">Instructions</div><ol style="margin: 0; padding-left: 16px; color: var(--lt-t-e2e8f0ff, #e2e8f0); line-height: 1.5;">${steps}</ol></div>` : ''}
        </div>
      </div>
    `;
  }
  return '';
}

export async function runAiRagAsk(rawQuestion, options = {}) {
  const askInput = document.getElementById('ai-rag-query-input');
  const q = (rawQuestion !== undefined && rawQuestion !== null ? String(rawQuestion) : (askInput ? askInput.value : '')).trim();
  if (!q) {
    showToast(t('ai.enter_question', 'Please enter a question or search query.'), 'warn');
    return null;
  }

  _recordAiSearchHistory(q);

  const scopeSelect = document.getElementById('ai-rag-scope-select');
  const scope = scopeSelect ? scopeSelect.value : 'all';

  const outTest = document.getElementById('ai-rag-answer-container');
  const emptyState = document.getElementById('ai-rag-empty-state');
  const answerCard = document.getElementById('ai-rag-answer-card');
  const structuredCardEl = document.getElementById('ai-rag-structured-card');
  const citationsGrid = document.getElementById('ai-rag-citations-grid');
  const askBtn = document.getElementById('btn-ai-rag-ask');
  const hasUnifiedVisualGrid = Boolean(document.getElementById('ai-visual-results-grid'));

  if (askBtn) {
    askBtn.disabled = true;
    askBtn.innerHTML = '<span aria-hidden="true">⏳</span> <span>Thinking...</span>';
  }
  const loadingHtml = `
    <div style="padding: 16px; text-align: center; color: var(--muted); font-size: 12px;">
      ✨ Searching local vector &amp; FTS5 index (Zero Disk Spindown Wake)...
    </div>
  `;
  if (outTest) outTest.innerHTML = loadingHtml;
  if (emptyState) emptyState.style.display = 'none';
  if (answerCard && !options.unifiedMode) {
    answerCard.style.display = 'block';
    answerCard.innerHTML = loadingHtml;
  }
  if (structuredCardEl) structuredCardEl.style.display = 'none';
  if (citationsGrid) citationsGrid.innerHTML = '';

  try {
    const res = await api.post('/api/media/ask', { query: q, scope, limit: 8 });
    if (!res) return null;

    const citations = res.citations || [];
    const photos = res.photos || res.visual_matches || [];
    const cards = res.structured_cards || (res.structured_card ? [res.structured_card] : []);

    const cardsHtml = cards.map((c) => renderStructuredCardHtml(c)).join('');

    const citationCardsListHtml = citations.map((c, idx) => {
      const cIdx = c.index || c.citation_index || (idx + 1);
      const fPath = c.file_path || c.path || '';
      const fName = c.file_name || c.name || 'Document';
      const secTitle = c.section_title || c.breadcrumb || fPath;
      const cleanExcerpt = String(c.excerpt || '').replace(/\s+/g, ' ').trim();
      return `
        <div class="ai-citation-card" data-path="${escapeHtml(fPath)}" data-name="${escapeHtml(fName)}" data-file-id="${c.file_id}" data-excerpt="${escapeHtml(cleanExcerpt)}" style="background: var(--lt-b-ffffff08, rgba(255,255,255,0.03)); border: 1px solid var(--lt-r-ffffff17, rgba(255,255,255,0.09)); border-radius: 8px; padding: 10px 12px; cursor: pointer; transition: border-color 0.2s;">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px;">
            <span style="font-weight: 700; font-size: 11.5px; color: var(--lt-t-38bdf8ff, #38bdf8);">[${cIdx}] 📄 ${escapeHtml(fName)}</span>
            <span style="font-size: 11px; padding: 1px 6px; border-radius: 4px; background: rgba(16,185,129,0.12); color: var(--lt-t-6ee7b7ff, #6ee7b7);">💤 Cached</span>
          </div>
          <div style="font-size: 11px; color: var(--muted); font-family: monospace; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(secTitle)}</div>
          <div style="font-size: 11px; color: var(--lt-t-cbd5e1ff, #cbd5e1); margin-top: 6px; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;">
            ${escapeHtml(cleanExcerpt)}
          </div>
        </div>
      `;
    }).join('');

    const citationsHtml = citations.length > 0
      ? `
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="font-size: 11px; font-weight: 800; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;">
            Grounded Document Citations (${citations.length})
          </div>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px;">
            ${citationCardsListHtml}
          </div>
        </div>
      `
      : '';

    const photosHtml = (photos.length > 0 && !(options.unifiedMode && hasUnifiedVisualGrid))
      ? `
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="font-size: 11px; font-weight: 800; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;">
            Matching Visual Assets (${photos.length})
          </div>
          <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(175px, 1fr)); gap: 10px;">
            ${photos.map((p) => buildVisualPhotoCardHtml(p)).join('')}
          </div>
        </div>
      `
      : '';

    const rawAnswerLines = String(res.answer || res.answer_markdown || 'No matching grounded context found.')
      .split('\n')
      .map((line) => line.replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    const answerFormatted = escapeHtml(rawAnswerLines.join('\n'))
      .replace(/\[\^(\d+):\s*([^\]]+)\]/g, '<span style="color:var(--lt-t-38bdf8ff, #38bdf8); font-weight:700;">[$1]</span> <strong>$2</strong> —')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\[(\d+)\]/g, '<span style="color:var(--lt-t-38bdf8ff, #38bdf8); font-weight:700;">[$1]</span>')
      .replace(/\n/g, '<br/>');

    const hwTierLabel = res.hardware?.tier_code || res.hardware?.tier || res.hardware?.active_tier_name || '—';
    const llmTel = res.llm_telemetry || {};
    const activeLlmId = llmTel.active_model || _aiLastActiveModel || '—';
    const tokPerSec = llmTel.tokens_per_sec || null;
    const combinedHtml = `
      <div class="ai-rag-synthesis-box" style="background: var(--lt-b-0f172aa6, rgba(15,23,42,0.65)); border: 1px solid rgba(56,189,248,0.28); border-radius: 10px; padding: 12px 15px; display: flex; flex-direction: column; gap: 10px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 15px;">🧠</span>
            <span style="font-weight: 800; font-size: 12.5px; color: var(--lt-t-ffffffff, #fff);">ZettAI Grounded Synthesis</span>
            <span class="ai-llm-proof-badge" style="font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: rgba(168,85,247,0.16); border: 1px solid rgba(192,132,252,0.45); color: var(--lt-t-e9d5ffff, #e9d5ff);" title="${escapeHtml(llmTel.runtime_mode || 'No AI model (built-in tools only)')}">🤖 ${escapeHtml(activeLlmId)}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 7px; font-size: 11px; color: var(--muted);">
            <span style="color: var(--lt-t-3bf58bff, #3bf58b); font-weight: 700;">⚡ ${escapeHtml(hwTierLabel)}</span>
            <span>•</span>
            ${tokPerSec ? `<span style="color: var(--lt-t-fde68aff, #fde68a);">🚀 ${tokPerSec} tok/s</span>` : ''}
            <span>•</span>
            <span>${res.elapsed_ms || llmTel.elapsed_ms || 0} ms</span>
            <span>•</span>
            <span style="color: var(--lt-t-6ee7b7ff, #6ee7b7);">💤 Standby Safe</span>
            <button type="button" class="btn-ai-dismiss-synthesis btn-pill-toggle is-small" style="margin-left: 4px;" title="${t('ui.hide_synthesis_card', 'Hide synthesis card')}">✕</button>
          </div>
        </div>
        <div style="font-size: 12px; color: var(--lt-t-f1f5f9ff, #f1f5f9); line-height: 1.55; max-height: 150px; overflow-y: auto;">
          ${answerFormatted}
        </div>
        ${cardsHtml}
        ${citationsHtml}
        ${photosHtml}
      </div>
    `;

    if (outTest) {
      outTest.innerHTML = combinedHtml;
      bindAiResultCardClicks(outTest);
    }
    if (answerCard) {
      const hasRecipeCard = cards.some((c) => (c.type || c.card_type) === 'recipe');
      const hasGroundedDocs = citations.length > 0 || hasRecipeCard;
      const isPhotoModality = res.parsed_intent?.modality_hint === 'photos'
        || _aiSelectedFileType === 'photos'
        || _aiSelectedFileType === 'videos'
        || _aiSelectedFileType === 'folders'
        || Boolean(_aiSelectedColor)
        || Boolean(_aiSelectedScene);
      if (options.unifiedMode && hasUnifiedVisualGrid && (!hasGroundedDocs || (isPhotoModality && !hasRecipeCard))) {
        answerCard.style.display = 'none';
        answerCard.innerHTML = '';
      } else {
        answerCard.style.display = 'block';
        answerCard.innerHTML = combinedHtml;
        bindAiResultCardClicks(answerCard);
        const dismissBtn = answerCard.querySelector('.btn-ai-dismiss-synthesis');
        if (dismissBtn) {
          dismissBtn.addEventListener('click', () => {
            answerCard.style.display = 'none';
          });
        }
      }
    }

    return res;
  } catch (err) {
    const errHtml = `<div style="padding: 16px; color: var(--crit, #ff5c5c); font-size: 12px;">RAG Query Error: ${escapeHtml(err.message || String(err))}</div>`;
    if (outTest) outTest.innerHTML = errHtml;
    if (answerCard && !options.unifiedMode) {
      answerCard.style.display = 'block';
      answerCard.innerHTML = errHtml;
    }
    return null;
  } finally {
    if (askBtn) {
      askBtn.disabled = false;
      askBtn.innerHTML = `<span aria-hidden="true">✨</span> <span data-i18n="ai.ask_btn">${escapeHtml(t('ai.ask_btn', 'Search & Ask'))}</span>`;
    }
  }
}

function buildVisualPhotoCardHtml(item) {
  const fId = item.file_id || item.id;
  const fPath = item.file_path || item.path || '';
  const fName = item.file_name || item.name || 'File';
  const fCat = item.file_category || 'photos';
  const isPhoto = fCat === 'photos' || (item.mime_type && String(item.mime_type).startsWith('image/'));
  const thumbUrl = item.thumbnail_url || `/api/media/thumbnail/${fId}`;
  const scenes = (item.scene_tags || []).slice(0, 4);
  const colors = (item.object_colors && item.object_colors.length ? item.object_colors : (item.dominant_colors || [])).slice(0, 3);
  const matchReason = item.match_reason || (isPhoto ? 'Visual + Semantic Match' : 'Semantic Match');
  const catIcon = fCat === 'videos' ? '🎬' : fCat === 'audio' ? '🎵' : fCat === 'documents' || fCat === 'recipes' ? '📄' : fCat === 'folders' ? '📁' : '📷';
  const isFav = Boolean(item.is_favorite);

  return `
    <div class="ai-visual-photo-card" data-path="${escapeHtml(fPath)}" data-name="${escapeHtml(fName)}" data-file-id="${fId}" data-category="${escapeHtml(fCat)}" data-favorite="${isFav ? '1' : '0'}" data-excerpt="${escapeHtml(item.excerpt || '')}" style="background: var(--lt-b-ffffff08, rgba(255,255,255,0.03)); border: 1px solid var(--lt-r-ffffff17, rgba(255,255,255,0.09)); border-radius: 9px; overflow: hidden; cursor: pointer; display: flex; flex-direction: column; transition: transform 0.15s, border-color 0.15s;">
      <div style="height: 125px; background: var(--lt-b-00000066, rgba(0,0,0,0.4)); position: relative; display: flex; align-items: center; justify-content: center; overflow: hidden;">
        ${isPhoto
          ? `<img src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(fName)}" loading="lazy" style="width: 100%; height: 100%; object-fit: cover;" data-img-fallback="hide" />`
          : `<div style="display:flex; flex-direction:column; align-items:center; gap:6px; padding:10px; text-align:center;">
               <span style="font-size:30px;">${catIcon}</span>
               <span style="font-size:11px; color:var(--lt-t-94a3b8ff, #94a3b8); max-height:42px; overflow:hidden;">${escapeHtml((item.excerpt || fPath).slice(0, 75))}</span>
             </div>`
        }
        <span title="${escapeHtml(matchReason)}" style="position: absolute; top: 6px; left: 6px; max-width: calc(100% - 82px); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: var(--lt-b-0f172ad9, rgba(15,23,42,0.85)); color: var(--lt-t-38bdf8ff, #38bdf8);">${catIcon} ${escapeHtml(matchReason)}</span>
        <span style="position: absolute; top: 6px; right: 6px; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: var(--lt-b-000000b8, rgba(0,0,0,0.72)); color: var(--lt-t-6ee7b7ff, #6ee7b7); white-space: nowrap;">${isFav ? '⭐ ' : ''}💤 Cached</span>
      </div>
      <div style="padding: 8px 10px; display: flex; flex-direction: column; gap: 4px;">
        <div style="font-weight: 700; font-size: 11.5px; color: var(--lt-t-ffffffff, #fff); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(fName)}">${escapeHtml(fName)}</div>
        <div style="font-size: 11px; color: var(--muted,#94a3b8); font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(fPath)}</div>
        <div style="display: flex; flex-wrap: wrap; gap: 4px;">
          ${colors.map((c) => `<span style="font-size: 11px; padding: 1px 5px; border-radius: 4px; background: rgba(56,189,248,0.14); color: var(--lt-t-38bdf8ff, #38bdf8); font-weight: 700; text-transform: capitalize;">🎨 ${escapeHtml(c)}</span>`).join('')}
          ${scenes.map((s) => `<span style="font-size: 11px; padding: 1px 5px; border-radius: 4px; background: var(--lt-b-ffffff12, rgba(255,255,255,0.07)); color: var(--lt-t-cbd5e1ff, #cbd5e1);">#${escapeHtml(s)}</span>`).join('')}
        </div>
      </div>
    </div>
  `;
}

export function renderAiPreviewInspector(item) {
  const pane = document.getElementById('ai-preview-inspector-pane');
  const splitLayout = document.getElementById('ai-search-split-layout');
  if (!pane || !item) return;

  const fId = item.file_id || item.id;
  const fPath = item.file_path || item.path || '';
  const fName = item.file_name || item.name || 'File';
  const fCat = item.file_category || 'photos';
  const isPhoto = fCat === 'photos';
  const thumbUrl = item.thumbnail_url || `/api/media/thumbnail/${fId}`;
  const parentDir = fPath.includes('/') ? (fPath.substring(0, fPath.lastIndexOf('/')) || '/') : '/mnt/user';
  const isFav = Boolean(item.is_favorite);

  pane.style.display = 'block';
  if (splitLayout) {
    splitLayout.style.gridTemplateColumns = 'minmax(0, 1fr) 320px';
  }

  pane.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:10px;">
      <div style="font-weight:800; font-size:12.5px; color:var(--lt-t-ffffffff, #fff); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(fName)}">
        ${escapeHtml(fName)}
      </div>
      <button type="button" id="btn-ai-inspector-close" class="btn-pill-toggle is-small">✕</button>
    </div>
    ${isPhoto
      ? `<div style="height:170px; border-radius:8px; background:var(--lt-b-00000073, rgba(0,0,0,0.45)); overflow:hidden; margin-bottom:10px; display:flex; align-items:center; justify-content:center;">
           <img src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(fName)}" style="width:100%; height:100%; object-fit:cover;" data-img-fallback="hide" />
         </div>`
      : ''
    }
    <div style="font-size:11px; color:var(--lt-t-cbd5e1ff, #cbd5e1); margin-bottom:10px; display:flex; flex-direction:column; gap:4px;">
      <div><strong style="color:var(--lt-t-94a3b8ff, #94a3b8);">Location:</strong> <code style="font-size:11px; color:var(--lt-t-38bdf8ff, #38bdf8); word-break:break-all;">${escapeHtml(fPath)}</code></div>
      <div><strong style="color:var(--lt-t-94a3b8ff, #94a3b8);">Match Mode:</strong> <span style="color:var(--lt-t-6ee7b7ff, #6ee7b7);">${escapeHtml(item.match_reason || 'Semantic Vector')}</span></div>
      ${item.excerpt ? `<div style="margin-top:4px; padding:8px; border-radius:6px; background:var(--lt-b-0000004c, rgba(0,0,0,0.3)); font-size:11px; color:var(--lt-t-e2e8f0ff, #e2e8f0); max-height:90px; overflow-y:auto;">${escapeHtml(item.excerpt)}</div>` : ''}
    </div>
    <!-- 5 Official ZettAI File Actions (#apps/zettai/search) -->
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
      <button type="button" id="btn-ai-inspector-open" class="btn-pill-toggle" style="background: rgba(14,165,233,0.22); border: 1px solid rgba(14,165,233,0.5); color: var(--lt-t-ffffffff, #fff);">
        👁️ Open File
      </button>
      <button type="button" id="btn-ai-inspector-location" class="btn-pill-toggle" style="background: rgba(37,194,160,0.18); border: 1px solid rgba(37,194,160,0.45); color: var(--lt-t-6ee7b7ff, #6ee7b7);" title="${t('ui.open_parent_folder_in_file', 'Open parent folder in File Manager')}">
        📂 Open Location
      </button>
      <button type="button" id="btn-ai-inspector-download" class="btn-pill-toggle">
        ⬇️ Download
      </button>
      <button type="button" id="btn-ai-inspector-favorite" class="btn-pill-toggle" style="font-size:11px; padding:6px 8px; cursor:pointer; color:${isFav ? '#fbbf24' : '#cbd5e1'};">
        ${isFav ? '⭐ Favorited' : '☆ Favorite'}
      </button>
      <button type="button" id="btn-ai-inspector-share" class="btn-pill-toggle" style="grid-column: 1 / -1;">
        🔗 Share File Path / Link
      </button>
    </div>
  `;

  const closeBtn = document.getElementById('btn-ai-inspector-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      pane.style.display = 'none';
      if (splitLayout) splitLayout.style.gridTemplateColumns = 'minmax(0, 1fr)';
    });
  }

  const openBtn = document.getElementById('btn-ai-inspector-open');
  if (openBtn) {
    openBtn.addEventListener('click', () => {
      if (typeof window.openFilePreviewModal === 'function') {
        window.openFilePreviewModal(fPath, fName, {
          standbySafe: true,
          fileId: fId,
          excerpt: item.excerpt || '',
          thumbnailUrl: fId ? `/api/media/thumbnail/${fId}` : null,
        });
      }
    });
  }

  const locBtn = document.getElementById('btn-ai-inspector-location');
  if (locBtn) {
    locBtn.addEventListener('click', () => {
      if (typeof window.openFileManager === 'function') {
        window.openFileManager(parentDir);
      } else {
        ZettEventBus.emit('window:open', { id: 'files', path: parentDir });
      }
      showToast(t('toast.opened_folder_location', 'Opened folder location: {parentDir}', { parentDir: parentDir }), 'info');
    });
  }

  const dlBtn = document.getElementById('btn-ai-inspector-download');
  if (dlBtn) {
    dlBtn.addEventListener('click', () => {
      const a = document.createElement('a');
      a.href = `/api/files/download?path=${encodeURIComponent(fPath)}`;
      a.download = fName;
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
  }

  const favBtn = document.getElementById('btn-ai-inspector-favorite');
  if (favBtn) {
    favBtn.addEventListener('click', async () => {
      try {
        const favRes = await api.post('/api/media/favorites', { file_path: fPath });
        if (favRes) {
          item.is_favorite = Boolean(favRes.is_favorite);
          renderAiPreviewInspector(item);
          showToast(item.is_favorite ? `Added "${fName}" to ZettAI Favorites ⭐` : `Removed "${fName}" from Favorites`, 'success');
        }
      } catch (err) {
        showToast(t('toast.failed_to_toggle_favorite', 'Failed to toggle favorite: {error}', { error: err.message }), 'error');
      }
    });
  }

  const shareBtn = document.getElementById('btn-ai-inspector-share');
  if (shareBtn) {
    shareBtn.addEventListener('click', async () => {
      const shareUrl = `${window.location.origin}/api/files/download?path=${encodeURIComponent(fPath)}`;
      try {
        await copyText(shareUrl);
        showToast(t('toast.copied_share_link_for_to_clipboard', 'Copied share link for {fName} to clipboard!', { fName: fName }), 'success');
      } catch (_) {
        showToast(t('toast.share_path', 'Share path: {fPath}', { fPath: fPath }), 'info');
      }
    });
  }
}

function bindAiResultCardClicks(container) {
  if (!container) return;
  container.querySelectorAll('.ai-citation-card, .ai-visual-photo-card').forEach((card) => {
    if (card.dataset.boundClick) return;
    card.dataset.boundClick = '1';
    card.addEventListener('click', () => {
      const filePath = card.dataset.path;
      const fileName = card.dataset.name;
      const fileId = card.dataset.fileId;
      const excerpt = card.dataset.excerpt;
      const matchedItem = _aiLastResultsList.find((r) => String(r.file_path || r.path) === String(filePath)) || {
        file_id: fileId,
        file_path: filePath,
        file_name: fileName,
        file_category: card.dataset.category || 'photos',
        excerpt,
        is_favorite: card.dataset.favorite === '1',
      };
      // Update split-pane preview inspector if inside the AI Visual/File Search tab
      if (card.closest('#ai-visual-results-grid')) {
        renderAiPreviewInspector(matchedItem);
      }
      if (typeof window.openFilePreviewModal === 'function') {
        window.openFilePreviewModal(filePath, fileName, {
          standbySafe: true,
          fileId,
          excerpt,
          thumbnailUrl: fileId ? `/api/media/thumbnail/${fileId}` : null,
        });
      }
    });
  });
}

function extractCategoryCount(groupObj) {
  if (Array.isArray(groupObj)) return groupObj.length;
  if (groupObj && typeof groupObj === 'object') {
    if (typeof groupObj.count === 'number') return groupObj.count;
    if (Array.isArray(groupObj.items)) return groupObj.items.length;
  }
  return Number(groupObj) || 0;
}

function renderAiCategorySummaryCards(groups = {}) {
  const entries = [
    { key: 'photos', mapGroup: 'images', icon: '📷', label: 'Images', count: extractCategoryCount(groups.images ?? groups.photos) },
    { key: 'videos', mapGroup: 'videos', icon: '🎬', label: 'Videos', count: extractCategoryCount(groups.videos) },
    { key: 'audio', mapGroup: 'audio', icon: '🎵', label: 'Audio', count: extractCategoryCount(groups.audio) },
    { key: 'documents', mapGroup: 'documents', icon: '📄', label: 'Documents', count: extractCategoryCount(groups.documents) },
    { key: 'folders', mapGroup: 'folders', icon: '📁', label: 'Folders', count: extractCategoryCount(groups.folders) },
  ];

  // Update live category counts directly inside the unified #ai-search-filetype-bar chips
  const countByType = new Map(entries.map((e) => [e.key, e]));
  document.querySelectorAll('#ai-search-filetype-bar .ai-filetype-chip').forEach((chip) => {
    const ft = chip.dataset.filetype;
    const entry = countByType.get(ft);
    if (entry) {
      chip.innerHTML = `${entry.icon} ${entry.label} <span style="opacity:0.75; font-size:11px; margin-left:2px;">(${entry.count})</span>`;
    }
  });

  const container = document.getElementById('ai-category-summary-cards');
  if (!container) return;
  // Keep #ai-category-summary-cards hidden in the unified omni-search layout since counts live in the Type pills
  container.style.display = 'none';
  container.innerHTML = '';
}

export function renderAiRagInitialEmptyState() {
  _aiSelectedColor = '';
  _aiSelectedScene = '';
  const grid = document.getElementById('ai-visual-results-grid');
  if (grid) {
    grid.innerHTML = `
      <div class="ai-rag-initial-placeholder" style="grid-column: 1 / -1; text-align: center; padding: 48px 20px; color: var(--muted, #94a3b8);">
        <div style="font-size: 32px; margin-bottom: 10px; opacity: 0.85;">🔍</div>
        <div style="font-size: 14px; font-weight: 600; color: var(--lt-t-e2e8f0ff, #e2e8f0); margin-bottom: 6px;" data-i18n="ai.search_placeholder_prompt">${escapeHtml(t('ai.search_placeholder_prompt', 'Search Your NAS Knowledge & Media'))}</div>
        <div style="font-size: 12px; color: var(--muted, #94a3b8); max-width: 480px; margin: 0 auto; line-height: 1.5;" data-i18n="ai.search_placeholder_sub">${escapeHtml(t('ai.search_placeholder_sub', 'Type a query above to search documents, recipes, photos, or audio, or ask Zetty a question. Results will appear here once you search.'))}</div>
      </div>
    `;
  }
  const banner = document.getElementById('ai-visual-intent-banner');
  if (banner) banner.style.display = 'none';
  const inspector = document.getElementById('ai-preview-inspector-pane');
  if (inspector) inspector.style.display = 'none';
  const splitLayout = document.getElementById('ai-search-split-layout');
  if (splitLayout) splitLayout.style.gridTemplateColumns = 'minmax(0, 1fr)';
  const answerCard = document.getElementById('ai-rag-answer-card');
  if (answerCard) answerCard.style.display = 'none';
  const structuredCard = document.getElementById('ai-rag-structured-card');
  if (structuredCard) structuredCard.style.display = 'none';
  const citationsGrid = document.getElementById('ai-rag-citations-grid');
  if (citationsGrid) citationsGrid.style.display = 'none';
  _aiLastResultsList = [];
}
export const _renderAiRagInitialEmptyState = renderAiRagInitialEmptyState;

export async function runAiVisualSearch(rawQuery = null) {
  const visInput = document.getElementById('ai-visual-search-input')
    || document.getElementById('ai-visual-query-input')
    || document.getElementById('ai-rag-query-input');
  const q = (rawQuery !== null ? rawQuery : (visInput ? visInput.value : '')).trim();
  const grid = document.getElementById('ai-visual-results-grid');
  if (!grid) return null;

  if (!q && !_aiSelectedColor && !_aiSelectedScene) {
    renderAiRagInitialEmptyState();
    return { status: 'ok', results: [] };
  }

  if (q) _recordAiSearchHistory(q);

  grid.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; padding: 24px; color: var(--muted); font-size: 12px;">🔍 Searching visual &amp; multi-modal index...</div>`;

  const modalityParam = _aiSelectedFileType === 'all' ? 'photo' : _aiSelectedFileType;

  try {
    const res = await api.post('/api/media/search', {
      query: q,
      modality: modalityParam,
      file_type: _aiSelectedFileType || 'all',
      match_tab: _aiSelectedMatchTab || 'semantic',
      sort_by: _aiSelectedSortBy || 'relevance',
      color: _aiSelectedColor || null,
      scene: _aiSelectedScene || null,
      limit: 24,
    });

    if (res?.category_groups) {
      renderAiCategorySummaryCards(res.category_groups);
    }

    const intentBanner = document.getElementById('ai-visual-intent-banner');
    if (intentBanner) {
      const autoColors = res?.parsed_intent?.auto_colors || (_aiSelectedColor ? [_aiSelectedColor] : []);
      const autoScenes = res?.parsed_intent?.auto_scenes || (_aiSelectedScene ? [_aiSelectedScene] : []);
      if (autoColors.length || autoScenes.length || q) {
        intentBanner.style.display = 'block';
        intentBanner.innerHTML = `
          <strong>🧠 Parsed Visual Intent:</strong>
          ${autoColors.length ? `<span style="margin-left:6px; color:var(--lt-t-38bdf8ff, #38bdf8);">🎨 Color: <b>${escapeHtml(autoColors.join(', '))}</b></span>` : ''}
          ${autoScenes.length ? `<span style="margin-left:8px; color:var(--lt-t-6ee7b7ff, #6ee7b7);">🏷️ Scene: <b>${escapeHtml(autoScenes.join(', '))}</b></span>` : ''}
          <span style="margin-left:8px; color:var(--lt-t-c7d2feff, #c7d2fe);">⚡ Mode: <b>${escapeHtml((_aiSelectedMatchTab || 'semantic').toUpperCase())}</b></span>
          <span style="margin-left:8px; color:var(--muted);">• 🛡️💤 Zero Disk Wakeups</span>
        `;
      } else {
        intentBanner.style.display = 'none';
      }
    }

    // The AI search model didn't answer: say these results match words only (AI-4)
    let degradedNote = document.getElementById('ai-search-degraded');
    if (res?.degraded) {
      if (!degradedNote) {
        degradedNote = document.createElement('div');
        degradedNote.id = 'ai-search-degraded';
        degradedNote.className = 'ai-search-degraded';
        degradedNote.setAttribute('role', 'status');
        grid.parentNode?.insertBefore(degradedNote, grid);
      }
      degradedNote.textContent = t('ai.search_degraded', "The AI search model didn't answer, so these results match words only. Try again in a moment.");
      degradedNote.hidden = false;
    } else if (degradedNote) {
      degradedNote.hidden = true;
    }

    const results = res?.results || res?.photo_results || res?.items || [];
    _aiLastResultsList = results;
    const immichStrip = document.getElementById('ai-immich-strip') || (() => {
      const el = document.createElement('div');
      el.id = 'ai-immich-strip';
      grid.parentNode?.insertBefore(el, grid);
      return el;
    })();
    immichStrip.innerHTML = immichResultsHtml(res?.immich_results);
    if (results.length === 0) {
      grid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 28px; color: var(--muted); font-size: 12px;">
          No matching files found for <strong>${escapeHtml(q || _aiSelectedColor || _aiSelectedScene || 'current filter')}</strong>. Click <strong>Sync Shares</strong> above or configure folders in the <em>⚙️ AI Configuration</em> tab.
        </div>
      `;
      return res;
    }

    grid.innerHTML = results.map((item) => buildVisualPhotoCardHtml(item)).join('');
    bindAiResultCardClicks(grid);
    return res;
  } catch (err) {
    grid.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; padding: 20px; color: var(--crit, #ff5c5c); font-size: 12px;">Visual search failed: ${escapeHtml(err.message || String(err))}</div>`;
    return null;
  }
}

export async function runAiPathIndex(targetPath = null, respectStandby = true) {
  const runBtns = [document.getElementById('btn-ai-run-index'), document.getElementById('btn-ai-run-index-path')].filter(Boolean);
  const feedbackEl = document.getElementById('ai-index-run-feedback');
  runBtns.forEach((b) => {
    b.disabled = true;
    b.innerHTML = '<span aria-hidden="true">⏳</span> <span>Indexing...</span>';
  });

  let targets;
  if (Array.isArray(targetPath) && targetPath.length > 0) {
    targets = targetPath.filter(Boolean);
  } else if (typeof targetPath === 'string' && targetPath.trim()) {
    targets = [targetPath.trim()];
  } else if (_aiWatchedPaths && _aiWatchedPaths.length > 0) {
    targets = [..._aiWatchedPaths];
  } else {
    targets = ['/mnt/user'];
  }

  const displayTarget = targets.length === 1 ? targets[0] : `${targets.length} watched folder(s)`;
  if (feedbackEl) {
    feedbackEl.textContent = `⏳ Scanning ${displayTarget} (Spindown-Safe Incremental Indexer)...`;
  }
  try {
    const res = await api.post('/api/media/index', {
      path: targets[0] || '/mnt/user',
      paths: targets,
      respect_standby: Boolean(respectStandby),
      recursive: true,
    });
    if (res) {
      const indexedCount = res.indexed ?? res.indexed_files ?? 0;
      const skippedCount = res.skipped_unchanged ?? 0;
      const deferredCount = res.deferred_standby ?? 0;
      const targetLabel = targets.length === 1 ? (res.path || targets[0]) : `${targets.length} watched folder(s)`;
      const msg = deferredCount > 0
        ? `Indexed ${indexedCount} file(s), ${skippedCount} unchanged (${deferredCount} deferred to protect sleeping drives).`
        : `Indexed ${indexedCount} file(s) (${skippedCount} unchanged) on ${targetLabel}.`;
      if (feedbackEl) {
        feedbackEl.textContent = `✓ ${msg}`;
      }
      showToast(msg, 'success');
      await fetchAndRenderAiStatus();
    }
    return res;
  } catch (err) {
    if (feedbackEl) {
      feedbackEl.textContent = `⚠️ Indexing failed: ${err.message}`;
    }
    showToast(t('toast.indexing_failed', 'Indexing failed: {error}', { error: err.message }), 'error');
    return null;
  } finally {
    runBtns.forEach((b) => {
      b.disabled = false;
      b.innerHTML = `<span aria-hidden="true">🚀</span> <span data-i18n="ai.run_index_btn">${escapeHtml(t('ai.run_index_btn', 'Index Path Now'))}</span>`;
    });
  }
}


// ZettAI proposes actions that change the system; they run only on this click (AI-01).
let _aiConfirmHandlerBound = false;
function _bindAiConfirmHandler() {
  if (_aiConfirmHandlerBound || typeof document === 'undefined') return;
  _aiConfirmHandlerBound = true;
  document.addEventListener('click', async (e) => {
    const btn = e.target?.closest?.('.ai-chat-confirm-action');
    if (!btn || btn.disabled) return;
    const actionId = btn.dataset.actionId;
    const row = btn.closest('.ai-chat-action-proposal');
    const status = row?.querySelector('.ai-chat-action-status');
    row?.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    if (btn.dataset.decision === 'cancel') {
      if (status) status.textContent = t('jobs.status_cancelled', 'Cancelled');
      return;
    }
    if (status) status.textContent = t('ui.running', 'Running...');
    try {
      const out = await api.post(`/api/ai/actions/${encodeURIComponent(actionId)}/confirm`, {});
      const ok = out && out.status === 'ok';
      if (status) status.textContent = ok ? `Done: ${out.message || out.summary || 'OK'}` : `Not run: ${out?.error || out?.status || 'unknown error'}`;
      showToast(ok ? `${out.summary || 'Action'} done` : `${out?.summary || 'Action'} failed: ${out?.error || ''}`, ok ? 'success' : 'error');
    } catch (err) {
      if (status) status.textContent = `Not run: ${err.message}`;
      showToast(t('toast.action_failed_2', 'Action failed: {error}', { error: err.message }), 'error');
    }
  });
}

function _buildAiActionProposalsHtml(toolsCalled) {
  const proposals = toolsCalled.filter((tc) => tc && tc.action_id && tc.status === 'confirmation_required');
  if (!proposals.length) return '';
  _bindAiConfirmHandler();
  return proposals.map((tc) => `
      <div class="ai-chat-action-proposal" style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:8px 10px; border-radius:8px; background:rgba(245,158,11,0.10); border:1px solid rgba(251,191,36,0.38);">
        <span style="font-size:12px; font-weight:700; color:var(--lt-t-fde68aff, #fde68a);">⏸️ ${escapeHtml(tc.action_summary || tc.tool)}</span>
        <button type="button" class="btn ai-chat-confirm-action" data-action-id="${escapeHtml(tc.action_id)}" data-decision="confirm" style="font-size:11px; padding:3px 10px;">Confirm</button>
        <button type="button" class="btn ai-chat-confirm-action" data-action-id="${escapeHtml(tc.action_id)}" data-decision="cancel" style="font-size:11px; padding:3px 10px; opacity:0.8;">Cancel</button>
        <span class="ai-chat-action-status" style="font-size:11px; color:var(--lt-t-cbd5e1ff, #cbd5e1);"></span>
      </div>`).join('');
}

function _buildAiExternalNoteHtml(res) {
  const ext = Array.isArray(res?.external_services) ? res.external_services : [];
  if (!ext.length) return '';
  return `<div class="ai-chat-external-note" style="font-size:11px; color:var(--lt-t-fbbf24ff, #fbbf24); padding-top:2px;" title="${t('ui.this_answer_used_services_outside', 'This answer used services outside your NAS')}">🌐 Data left this device: ${escapeHtml(ext.join(', '))}</div>`;
}

// Remember the Web toggle per browser (a convenience; the server default is off).
function _initAiWebToggle() {
  const el = document.getElementById('ai-chat-web-toggle');
  if (!el || el.dataset.bound) return;
  el.dataset.bound = '1';
  try {
    el.checked = localStorage.getItem('zettnas_ai_web') === '1';
  } catch (e) { /* storage blocked */ }
  el.addEventListener('change', () => {
    try {
      localStorage.setItem('zettnas_ai_web', el.checked ? '1' : '0');
    } catch (e) { /* storage blocked */ }
  });
}
if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', _initAiWebToggle);
  else _initAiWebToggle();
}

function _buildAiAssistantMessageHtml(res, defaultModel) {
  const replyMd = res.reply || res.answer || 'No response generated.';
  const llmTel = res.llm_telemetry || {};
  const toolsCalled = Array.isArray(res.tools_called) ? res.tools_called : [];
  const webSources = Array.isArray(res.web_sources) ? res.web_sources : [];
  const citations = Array.isArray(res.citations) ? res.citations : [];
  const photos = Array.isArray(res.photos) ? res.photos : [];
  const folderPath = res.folder_path || '';
  const folderManifest = res.folder_manifest || null;
  const groundingScore = res.grounding_confidence_score != null ? res.grounding_confidence_score : null;
  const cragGrade = res.crag_grade || '';
  const usedModel = llmTel.active_model || res.active_model || defaultModel;
  const accelLabel = llmTel.accelerator_label || '—';
  const runtimeMode = llmTel.runtime_mode || 'No AI model (built-in tools only)';
  const tokSec = llmTel.tokens_per_sec || null;
  const elapsedMs = res.elapsed_ms || llmTel.elapsed_ms || 0;

  const toolsBadgesHtml = toolsCalled.length > 0
    ? `
      <div class="ai-chat-tools-trace" style="display: flex; flex-wrap: wrap; gap: 5px; padding-top: 2px;">
        ${toolsCalled.map((tc) => {
          const isWeb = tc.tool === 'browse_internet';
          const isRag = tc.tool === 'search_nas_knowledge';
          const isCalc = tc.tool === 'calculate';
          const isStorage = tc.tool === 'get_storage_status';
          const isNet = tc.tool === 'get_network_status';
          const isWeather = tc.tool === 'get_weather';
          const bg = isCalc ? 'rgba(245,158,11,0.16)' : (isWeather ? 'rgba(14,165,233,0.18)' : (isWeb ? 'rgba(56,189,248,0.16)' : (isRag ? 'rgba(168,85,247,0.16)' : (isNet ? 'rgba(14,165,233,0.16)' : 'rgba(16,185,129,0.16)'))));
          const border = isCalc ? 'rgba(251,191,36,0.42)' : (isWeather ? 'rgba(56,189,248,0.45)' : (isWeb ? 'rgba(56,189,248,0.42)' : (isRag ? 'rgba(168,85,247,0.42)' : (isNet ? 'rgba(56,189,248,0.42)' : 'rgba(52,211,153,0.42)'))));
          const color = isCalc ? '#fde68a' : (isWeather ? '#38bdf8' : (isWeb ? '#7dd3fc' : (isRag ? '#d8b4fe' : (isNet ? '#7dd3fc' : '#6ee7b7'))));
          const icon = isCalc ? '🧮' : (isWeather ? '⛅' : (isWeb ? '🌐' : (isRag ? '📁' : (isStorage ? '💽' : (isNet ? '🔌' : '🛠️')))));
          return `<span class="ai-chat-tool-pill" data-tool-name="${escapeHtml(tc.tool)}" style="font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: ${bg}; border: 1px solid ${border}; color: ${color};" title="${escapeHtml(tc.summary || tc.tool)}">${icon} ${escapeHtml(tc.tool)}: ${escapeHtml(tc.summary || 'OK')}</span>`;
        }).join('')}
      </div>
    `
    : '';

  const folderBannerHtml = folderPath
    ? `
      <div class="ai-chat-folder-banner" style="display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; padding: 6px 10px; border-radius: 8px; background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.28); margin-bottom: 2px;">
        <div style="display: flex; align-items: center; gap: 6px; font-size: 11px;">
          <span aria-hidden="true">📁</span>
          <span style="font-weight: 700; color: var(--lt-t-7dd3fcff, #7dd3fc);">Folder Scope:</span>
          <code style="color: var(--lt-t-e0f2feff, #e0f2fe); font-size: 11px; background: var(--lt-b-00000040, rgba(0,0,0,0.25)); padding: 1px 5px; border-radius: 4px;">${escapeHtml(folderPath)}</code>
          ${folderManifest && folderManifest.total_files ? `<span style="font-size: 11px; color: var(--lt-t-94a3b8ff, #94a3b8);">(${folderManifest.total_files} files)</span>` : ''}
        </div>
        ${groundingScore === null ? `
          <div style="display: flex; align-items: center; gap: 5px;">
            <span style="font-size: 11px; font-weight: 700; color: var(--lt-t-cbd5e1ff, #cbd5e1); background: rgba(148,163,184,0.14); border: 1px solid rgba(148,163,184,0.35); padding: 1px 7px; border-radius: 999px;" title="${t('ui.this_answer_s_support_in', 'This answer\'s support in the sources wasn\'t measured.')}">Unverified</span>
          </div>
        ` : ''}
        ${groundingScore !== null ? `
          <div style="display: flex; align-items: center; gap: 5px;">
            <span style="font-size: 11px; font-weight: 800; color: ${groundingScore >= 80 ? '#34d399' : (groundingScore >= 50 ? '#fbbf24' : '#f87171')}; background: ${groundingScore >= 80 ? 'rgba(52,211,153,0.14)' : 'rgba(251,191,36,0.14)'}; border: 1px solid ${groundingScore >= 80 ? 'rgba(52,211,153,0.35)' : 'rgba(251,191,36,0.35)'}; padding: 1px 7px; border-radius: 999px;">
              🎯 ${res.grounding_detail
                ? escapeHtml(t('ai.grounded_sentences', '{n} of {total} sentences backed by the sources', { n: res.grounding_detail.supported, total: res.grounding_detail.total }))
                : `${groundingScore}% Grounded (${escapeHtml(cragGrade.toUpperCase() || 'HIGH')})`}
            </span>
            ${unsupportedHtml(res.grounding_detail)}
          </div>
        ` : ''}
      </div>
    `
    : '';

  const docCitationsHtml = citations.length > 0
    ? `
      <details class="ai-chat-doc-citations" style="margin-top: 4px; font-size: 11px;">
        <summary style="cursor: pointer; color: var(--lt-t-38bdf8ff, #38bdf8); font-weight: 700; display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px; border-radius: 6px; background: rgba(56,189,248,0.12); border: 1px solid rgba(56,189,248,0.32); width: fit-content; user-select: none;">
          <span>📚 Verified Citations (${citations.length})</span>
        </summary>
        <div style="margin-top: 8px; display: flex; flex-direction: column; gap: 6px;">
          ${citations.map((c, idx) => {
            const cname = c.name || (c.path ? c.path.split('/').pop() : 'Document');
            const bcrumb = c.breadcrumb ? ` > ${c.breadcrumb}` : '';
            const scorePct = Math.round(Number(c.score || 0.9) * 100);
            const escPath = escapeHtml(c.path || '');
            const escName = escapeHtml(cname);
            return `
              <div class="ai-citation-card" style="padding: 7px 10px; border-radius: 7px; background: var(--lt-b-0f172ad9, rgba(15,23,42,0.85)); border: 1px solid rgba(56,189,248,0.22); font-size: 11px;">
                <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px; margin-bottom: 3px;">
                  <button type="button" class="btn-preview-citation" data-action="open-file-preview" data-path="${escPath}" data-name="${escName}" style="background: none; border: none; padding: 0; color: var(--lt-t-38bdf8ff, #38bdf8); font-weight: 700; cursor: pointer; text-decoration: underline; text-align: left; font-size: 11.5px;">
                    📄 [${idx + 1}] ${escName}<span style="color: var(--lt-t-94a3b8ff, #94a3b8); font-weight: 400; text-decoration: none;">${escapeHtml(bcrumb)}</span> 👁️
                  </button>
                  <span style="font-size: 11px; color: var(--lt-t-a7f3d0ff, #a7f3d0); background: rgba(16,185,129,0.14); padding: 1px 6px; border-radius: 999px;">${scorePct}% match</span>
                </div>
                ${c.excerpt ? `<div style="color: var(--lt-t-cbd5e1ff, #cbd5e1); font-size: 11px; line-height: 1.45; font-style: italic; background: var(--lt-b-00000040, rgba(0,0,0,0.25)); padding: 5px 8px; border-radius: 5px; border-left: 2px solid #38bdf8;">"${escapeHtml(c.excerpt)}"</div>` : ''}
              </div>
            `;
          }).join('')}
        </div>
      </details>
    `
    : '';

  const photosHtml = photos.length > 0
    ? `
      <div class="ai-chat-photos-grid" style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px;">
        ${photos.map((p) => {
          const escP = escapeHtml(p.path || '');
          const escN = escapeHtml(p.name || 'Photo');
          const thumb = p.thumbnail_url || (p.file_id ? `/api/media/thumbnail/${p.file_id}` : '');
          return `
            <div class="ai-chat-photo-card" data-action="open-file-preview" data-path="${escP}" data-name="${escN}" style="cursor: pointer; width: 85px; border-radius: 6px; overflow: hidden; background: var(--lt-b-00000066, rgba(0,0,0,0.4)); border: 1px solid var(--lt-r-ffffff1a, rgba(255,255,255,0.1)); transition: transform 0.15s ease;" title="${escN}">
              ${thumb ? `<img src="${escapeHtml(thumb)}" alt="${escN}" style="width: 100%; height: 60px; object-fit: cover;" />` : `<div style="height: 60px; display: flex; align-items: center; justify-content: center; font-size: 20px;">🖼️</div>`}
              <div style="font-size: 11px; color: var(--lt-t-cbd5e1ff, #cbd5e1); padding: 2px 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escN}</div>
            </div>
          `;
        }).join('')}
      </div>
    `
    : '';

  const webSourcesHtml = webSources.length > 0
    ? `
      <details class="ai-chat-web-sources" style="margin-top: 2px; font-size: 11px;">
        <summary style="cursor: pointer; color: var(--lt-t-94a3b8ff, #94a3b8); font-weight: 600; display: inline-flex; align-items: center; gap: 4px; padding: 2px 7px; border-radius: 6px; background: var(--lt-b-ffffff08, rgba(255,255,255,0.03)); border: 1px solid var(--lt-r-ffffff14, rgba(255,255,255,0.08)); width: fit-content; user-select: none;">
          <span>🌐 Sources (${webSources.length})</span>
        </summary>
        <div style="margin-top: 6px; display: flex; flex-wrap: wrap; gap: 5px; padding-left: 2px;">
          ${webSources.slice(0, 5).map((ws) => `<a href="${escapeHtml(ws.url)}" target="_blank" rel="noopener noreferrer" style="padding: 2px 8px; border-radius: 6px; background: rgba(56,189,248,0.12); border: 1px solid rgba(56,189,248,0.32); color: var(--lt-t-38bdf8ff, #38bdf8); text-decoration: none; font-weight: 600; font-size: 11px;">${escapeHtml(ws.title || ws.source || 'Source')} ↗</a>`).join('')}
        </div>
      </details>
    `
    : '';

  return `
    <div class="ai-chat-llm-proof-bar" style="display: flex; justify-content: space-between; align-items: center; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid var(--lt-r-ffffff0f, rgba(255,255,255,0.06)); padding-bottom: 5px;">
      <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
        <span class="ai-chat-model-pill" style="font-size: 11px; font-weight: 800; color: var(--lt-t-e9d5ffff, #e9d5ff); padding: 1px 8px; border-radius: 999px; background: rgba(168,85,247,0.18); border: 1px solid rgba(192,132,252,0.45);">🤖 ${escapeHtml(usedModel)}</span>
        <span style="font-size: 11px; font-weight: 700; color: var(--lt-t-3bf58bff, #3bf58b);">⚡ ${escapeHtml(accelLabel)}</span>
        <span style="font-size: 11px; color: var(--lt-t-94a3b8ff, #94a3b8);">(${escapeHtml(runtimeMode)})</span>
      </div>
      <div style="display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--lt-t-94a3b8ff, #94a3b8);">
        ${!folderPath && groundingScore !== null ? `<span style="font-size: 11px; font-weight: 700; color: var(--lt-t-34d399ff, #34d399); padding: 0 5px; border-radius: 999px; background: rgba(52,211,153,0.12); border: 1px solid rgba(52,211,153,0.3);">🎯 ${groundingScore}% Grounded</span><span>•</span>` : ''}
        ${tokSec ? `<span style="color: var(--lt-t-fde68aff, #fde68a);">🚀 ${tokSec} tok/s</span>` : ''}
        <span>•</span>
        <span>${elapsedMs} ms</span>
      </div>
    </div>
    ${toolsBadgesHtml}
    ${_buildAiExternalNoteHtml(res)}
    ${_buildAiActionProposalsHtml(toolsCalled)}
    ${folderBannerHtml}
    <div class="ai-chat-reply-body" style="font-size: 12px; color: var(--lt-t-f1f5f9ff, #f1f5f9); line-height: 1.55;">
      ${_formatChatMarkdown(replyMd, { citations, webSources })}
    </div>
    ${docCitationsHtml}
    ${photosHtml}
    ${webSourcesHtml}
  `;
}

let _activeConversationId = null;
let _activeConversationTitle = 'New Conversation';
let _aiConversations = [];
let _aiActiveAbortController = null;
let _aiActiveRequestId = 0;
let _aiStopRequested = false;

function _groupConversationsChronologically(convs) {
  const now = Date.now();
  const oneDayMs = 24 * 60 * 60 * 1000;
  const groups = {
    pinned: [],
    today: [],
    yesterday: [],
    prev7Days: [],
    older: [],
  };

  convs.forEach((c) => {
    if (c.is_pinned) {
      groups.pinned.push(c);
      return;
    }
    const updatedMs = (c.updated_at || c.created_at || (now / 1000)) * 1000;
    const diffMs = now - updatedMs;
    const diffDays = Math.floor(diffMs / oneDayMs);

    if (diffDays === 0) {
      groups.today.push(c);
    } else if (diffDays === 1) {
      groups.yesterday.push(c);
    } else if (diffDays <= 7) {
      groups.prev7Days.push(c);
    } else {
      groups.older.push(c);
    }
  });

  return groups;
}

export async function fetchAndRenderAiConversations(searchQuery = '') {
  const listContainer = document.getElementById('ai-chat-threads-list');
  const countBadge = document.getElementById('ai-chat-thread-count');
  if (!listContainer) return;

  try {
    const res = await api.get('/api/ai/conversations', searchQuery ? { search: searchQuery } : {});
    const convs = (res && res.conversations) ? res.conversations : [];
    _aiConversations = convs;

    if (countBadge) {
      countBadge.textContent = `${convs.length} ${convs.length === 1 ? 'chat' : 'chats'}`;
    }

    if (convs.length === 0) {
      listContainer.innerHTML = `<div class="ai-empty-threads">${escapeHtml(t('ai.no_chats', 'No conversations yet'))}</div>`;
      return;
    }

    const groups = _groupConversationsChronologically(convs);
    let html = '';

    const renderGroup = (labelKey, defaultLabel, items, icon) => {
      if (!items || items.length === 0) return '';
      let gHtml = `<div class="ai-thread-group-header"><span>${icon}</span> <span>${escapeHtml(t(labelKey, defaultLabel))}</span></div>`;
      items.forEach((c) => {
        const isActive = c.id === _activeConversationId;
        const pinIcon = c.is_pinned ? '📌' : '📍';
        const pinTitle = c.is_pinned ? 'Unpin' : 'Pin';
        gHtml += `
          <div class="ai-thread-item ${isActive ? 'active' : ''}" data-conv-id="${escapeHtml(c.id)}">
            <span class="ai-thread-title-text" title="${escapeHtml(c.title || 'New Conversation')}">${escapeHtml(c.title || 'New Conversation')}</span>
            <div class="ai-thread-actions">
              <button type="button" class="btn-ai-thread-action btn-ai-thread-pin" data-conv-id="${escapeHtml(c.id)}" data-pinned="${c.is_pinned ? '1' : '0'}" title="${pinTitle}">${pinIcon}</button>
              <button type="button" class="btn-ai-thread-action btn-ai-thread-rename" data-conv-id="${escapeHtml(c.id)}" title="${t('mgmt.wallpaper_rename', 'Rename')}">✏️</button>
              <button type="button" class="btn-ai-thread-action btn-ai-thread-del" data-conv-id="${escapeHtml(c.id)}" title="${t('vm.delete', 'Delete')}">🗑️</button>
            </div>
          </div>
        `;
      });
      return gHtml;
    };

    html += renderGroup('ai.pinned', 'Pinned', groups.pinned, '📌');
    html += renderGroup('ai.today', 'Today', groups.today, '📅');
    html += renderGroup('ai.yesterday', 'Yesterday', groups.yesterday, '⏳');
    html += renderGroup('ai.prev_7_days', 'Previous 7 Days', groups.prev7Days, '📆');
    html += renderGroup('ai.older', 'Older', groups.older, '🗄️');

    listContainer.innerHTML = html;

    listContainer.querySelectorAll('.ai-thread-item').forEach((item) => {
      const cid = item.dataset.convId;
      item.addEventListener('click', (e) => {
        if (e.target.closest('.ai-thread-actions')) return;
        selectAiConversation(cid);
        // on a phone the list covers the chat: close it once a conversation is picked
        const sidebar = document.getElementById('ai-chat-sidebar');
        if (document.body.classList.contains('phone-shell') && sidebar && !sidebar.classList.contains('collapsed')) toggleAiSidebar();
      });
    });

    listContainer.querySelectorAll('.btn-ai-thread-pin').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const cid = btn.dataset.convId;
        const isPinned = btn.dataset.pinned === '1';
        try {
          await api.patch(`/api/ai/conversations/${cid}`, { is_pinned: !isPinned });
          await fetchAndRenderAiConversations(searchQuery);
        } catch (err) {
          showToast(t('toast.pin_failed', 'Pin failed: {error}', { error: err.message }), 'error');
        }
      });
    });

    listContainer.querySelectorAll('.btn-ai-thread-rename').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        renameAiConversation(btn.dataset.convId);
      });
    });

    listContainer.querySelectorAll('.btn-ai-thread-del').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteAiConversation(btn.dataset.convId);
      });
    });

    if (!_activeConversationId && convs.length > 0) {
      selectAiConversation(convs[0].id);
    }
  } catch (err) {
    console.debug('[ZettAI] Failed loading conversations:', err);
  }
}

export async function selectAiConversation(convId) {
  if (!convId) return;
  if (_aiActiveAbortController) {
    _aiActiveAbortController.abort();
    _aiActiveAbortController = null;
  }
  _activeConversationId = convId;

  document.querySelectorAll('.ai-thread-item').forEach((el) => {
    el.classList.toggle('active', el.dataset.convId === convId);
  });

  const listEl = document.getElementById('ai-chat-messages-list');
  const titleEl = document.getElementById('ai-chat-active-title');

  try {
    const res = await api.get(`/api/ai/conversations/${convId}`);
    if (!res || !res.conversation) return;
    const conv = res.conversation;
    _activeConversationTitle = conv.title || 'New Conversation';
    if (titleEl) titleEl.textContent = _activeConversationTitle;

    if (!listEl) return;
    listEl.innerHTML = '';
    _aiChatHistory = [];

    const msgs = conv.messages || [];
    msgs.forEach((m) => {
      _aiChatHistory.push({ role: m.role, content: m.content });
      if (m.role === 'user') {
        const userMsgEl = document.createElement('div');
        userMsgEl.className = 'ai-chat-msg ai-chat-msg-user';
        userMsgEl.dataset.convId = convId;
        userMsgEl.style.cssText = 'align-self: flex-end; max-width: 85%; padding: 9px 13px; border-radius: 10px; background: rgba(14, 165, 233, 0.22); border: 1px solid rgba(56, 189, 248, 0.45); color: #f8fafc; font-size: 12px; line-height: 1.45;';
        userMsgEl.innerHTML = `<div style="font-size:11px; font-weight:700; color:var(--lt-t-7dd3fcff, #7dd3fc); margin-bottom:3px;">🧑 You</div><div>${escapeHtml(m.content)}</div>`;
        listEl.appendChild(userMsgEl);
      } else if (m.role === 'assistant') {
        const botMsgEl = document.createElement('div');
        botMsgEl.className = 'ai-chat-msg ai-chat-msg-assistant';
        botMsgEl.dataset.convId = convId;
        const modelName = m.telemetry?.active_model || conv.model || '—';
        botMsgEl.innerHTML = _buildAiAssistantMessageHtml({
          reply: m.content,
          llm_telemetry: m.telemetry,
          tools_called: m.tools_called,
          web_sources: m.web_sources,
          citations: m.citations,
          photos: m.photos,
        }, modelName);
        listEl.appendChild(botMsgEl);
      }
    });

    listEl.scrollTop = listEl.scrollHeight;
  } catch (err) {
    console.debug('[ZettAI] Failed selecting conversation:', err);
  }
}

export async function createNewAiConversation() {
  if (_aiActiveAbortController) {
    _aiActiveAbortController.abort();
    _aiActiveAbortController = null;
  }
  try {
    const res = await api.post('/api/ai/conversations', { title: 'New Conversation' });
    if (res && res.conversation) {
      _activeConversationId = res.conversation.id;
      _activeConversationTitle = res.conversation.title || 'New Conversation';
      const titleEl = document.getElementById('ai-chat-active-title');
      if (titleEl) titleEl.textContent = _activeConversationTitle;
      const listEl = document.getElementById('ai-chat-messages-list');
      if (listEl) listEl.innerHTML = '';
      _aiChatHistory = [];
      await fetchAndRenderAiConversations();
      const inputEl = document.getElementById('ai-chat-input');
      if (inputEl) inputEl.focus();
    }
  } catch (err) {
    showToast(t('toast.could_not_start_new_chat', 'Could not start new chat: {error}', { error: err.message }), 'error');
  }
}

export async function renameAiConversation(convId, customTitle = null) {
  const targetId = convId || _activeConversationId;
  if (!targetId) return;

  let currentTitle = _activeConversationTitle;
  const match = _aiConversations.find((c) => c.id === targetId);
  if (match && match.title) currentTitle = match.title;

  const performRename = async (titleToSet) => {
    if (!titleToSet || !titleToSet.trim()) return;
    try {
      await api.patch(`/api/ai/conversations/${targetId}`, { title: titleToSet.trim() });
      if (targetId === _activeConversationId) {
        _activeConversationTitle = titleToSet.trim();
        const titleEl = document.getElementById('ai-chat-active-title');
        if (titleEl) titleEl.textContent = _activeConversationTitle;
      }
      await fetchAndRenderAiConversations();
      showToast(t('ai.chat_renamed', 'Conversation renamed.'), 'success');
    } catch (err) {
      showToast(t('toast.rename_failed', 'Rename failed: {error}', { error: err.message }), 'error');
    }
  };

  if (customTitle !== null) {
    await performRename(customTitle);
    return;
  }

  showPromptToast(
    t('ai.rename_chat', 'Rename Chat'),
    t('ai.rename_chat_prompt', 'Enter a new title for this conversation:'),
    currentTitle,
    async (val) => {
      await performRename(val);
    },
    null,
    {
      okText: t('common.save', 'Save'),
      cancelText: t('common.cancel', 'Cancel'),
      icon: '✏️',
    }
  );
}

export async function deleteAiConversation(convId) {
  const targetId = convId || _activeConversationId;
  if (!targetId) return;

  showConfirmToast(
    t('ai.delete_chat', 'Delete Conversation'),
    t('ai.confirm_delete_chat', 'Are you sure you want to delete this conversation?'),
    async () => {
      try {
        await api.delete(`/api/ai/conversations/${targetId}`);
        showToast(t('ai.chat_deleted', 'Conversation deleted.'), 'success');
        if (targetId === _activeConversationId) {
          _activeConversationId = null;
          _activeConversationTitle = 'New Conversation';
          const titleEl = document.getElementById('ai-chat-active-title');
          if (titleEl) titleEl.textContent = t('ui.new_conversation', 'New Conversation');
          const listEl = document.getElementById('ai-chat-messages-list');
          if (listEl) listEl.innerHTML = '';
          _aiChatHistory = [];
        }
        await fetchAndRenderAiConversations();
        if (!_activeConversationId && _aiConversations.length > 0) {
          selectAiConversation(_aiConversations[0].id);
        } else if (!_activeConversationId) {
          await createNewAiConversation();
        }
      } catch (err) {
        showToast(t('toast.delete_failed', 'Delete failed: {error}', { error: err.message }), 'error');
      }
    }
  );
}

export async function clearAllAiConversations() {
  showConfirmToast(
    t('ai.clear_all', 'Clear All Conversations'),
    t('ai.confirm_clear_all', 'Are you sure you want to delete all conversation history?'),
    async () => {
      try {
        await api.delete('/api/ai/conversations');
        _activeConversationId = null;
        _activeConversationTitle = 'New Conversation';
        _aiConversations = [];
        _aiChatHistory = [];
        const listEl = document.getElementById('ai-chat-messages-list');
        if (listEl) listEl.innerHTML = '';
        showToast(t('ai.all_cleared', 'All conversations cleared.'), 'success');
        await createNewAiConversation();
      } catch (err) {
        showToast(t('toast.clear_all_failed', 'Clear all failed: {error}', { error: err.message }), 'error');
      }
    }
  );
}

export async function exportActiveAiThread(format = 'markdown') {
  if (!_activeConversationId) {
    showToast(t('ai.no_active_conversation', 'No active conversation to export.'), 'warn');
    return;
  }
  try {
    const res = await api.get(`/api/ai/conversations/${_activeConversationId}`);
    if (!res || !res.conversation) return;
    const conv = res.conversation;
    const title = conv.title || 'Conversation';
    const dateStr = formatDateTime(conv.created_at || Date.now());

    let content = '';
    let mimeType = 'text/plain';
    let ext = 'txt';

    if (format === 'markdown') {
      mimeType = 'text/markdown';
      ext = 'md';
      content = `# ${title}\n*Exported from ZettAI on ${dateStr}*\n\n---\n\n`;
      (conv.messages || []).forEach((m) => {
        if (m.role === 'user') {
          content += `### 🧑 User:\n${m.content}\n\n`;
        } else if (m.role === 'assistant') {
          content += `### 🤖 ZettAI:\n${m.content}\n\n`;
        }
      });
    } else {
      mimeType = 'application/json';
      ext = 'json';
      content = JSON.stringify(conv, null, 2);
    }

    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const cleanFileName = title.toLowerCase().replace(/[^a-z0-9_-]/g, '_').slice(0, 40) || 'chat';
    a.download = `zettai_${cleanFileName}.${ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast(t('toast.exported_conversation_as', 'Exported conversation as {ext}', { ext: ext.toUpperCase() }), 'success');
  } catch (err) {
    showToast(t('toast.export_failed', 'Export failed: {error}', { error: err.message }), 'error');
  }
}

export function toggleAiSidebar() {
  const sidebar = document.getElementById('ai-chat-sidebar');
  const openBtn = document.getElementById('btn-ai-chat-sidebar-open');
  if (!sidebar) return;
  const isCollapsed = sidebar.classList.toggle('collapsed');
  if (openBtn) {
    openBtn.style.display = isCollapsed ? 'flex' : 'none';
  }
  try {
    localStorage.setItem('zettnas_ai_sidebar_collapsed', isCollapsed ? '1' : '0');
  } catch (_) {}
}

export function initAiConversationControls() {
  const btnNew = document.getElementById('btn-ai-chat-new');
  if (btnNew && !btnNew.dataset.bound) {
    btnNew.dataset.bound = '1';
    btnNew.addEventListener('click', () => createNewAiConversation());
  }

  const btnToggle = document.getElementById('btn-ai-chat-sidebar-toggle');
  if (btnToggle && !btnToggle.dataset.bound) {
    btnToggle.dataset.bound = '1';
    btnToggle.addEventListener('click', () => toggleAiSidebar());
  }

  const btnOpen = document.getElementById('btn-ai-chat-sidebar-open');
  if (btnOpen && !btnOpen.dataset.bound) {
    btnOpen.dataset.bound = '1';
    btnOpen.addEventListener('click', () => toggleAiSidebar());
  }

  const searchInput = document.getElementById('ai-chat-search-input');
  if (searchInput && !searchInput.dataset.bound) {
    searchInput.dataset.bound = '1';
    let debounceTimer = null;
    searchInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        fetchAndRenderAiConversations(searchInput.value.trim());
      }, 200);
    });
  }

  const btnClearAll = document.getElementById('btn-ai-chat-clear-all');
  if (btnClearAll && !btnClearAll.dataset.bound) {
    btnClearAll.dataset.bound = '1';
    btnClearAll.addEventListener('click', () => clearAllAiConversations());
  }

  const btnRename = document.getElementById('btn-ai-chat-rename');
  if (btnRename && !btnRename.dataset.bound) {
    btnRename.dataset.bound = '1';
    btnRename.addEventListener('click', () => renameAiConversation(_activeConversationId));
  }

  const titleEl = document.getElementById('ai-chat-active-title');
  if (titleEl && !titleEl.dataset.bound) {
    titleEl.dataset.bound = '1';
    titleEl.addEventListener('dblclick', () => renameAiConversation(_activeConversationId));
  }

  const exportToggle = document.getElementById('btn-ai-chat-export-toggle');
  const exportMenu = document.getElementById('ai-chat-export-menu');
  if (exportToggle && exportMenu && !exportToggle.dataset.bound) {
    exportToggle.dataset.bound = '1';
    exportToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      exportMenu.style.display = exportMenu.style.display === 'none' ? 'block' : 'none';
    });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#ai-chat-export-menu') && !e.target.closest('#btn-ai-chat-export-toggle')) {
        exportMenu.style.display = 'none';
      }
    });
  }

  const btnExportMd = document.getElementById('btn-ai-chat-export-md');
  if (btnExportMd && !btnExportMd.dataset.bound) {
    btnExportMd.dataset.bound = '1';
    btnExportMd.addEventListener('click', () => {
      if (exportMenu) exportMenu.style.display = 'none';
      exportActiveAiThread('markdown');
    });
  }

  const btnExportJson = document.getElementById('btn-ai-chat-export-json');
  if (btnExportJson && !btnExportJson.dataset.bound) {
    btnExportJson.dataset.bound = '1';
    btnExportJson.addEventListener('click', () => {
      if (exportMenu) exportMenu.style.display = 'none';
      exportActiveAiThread('json');
    });
  }

  try {
    // On a phone the list starts closed: open, it covers the chat (56-phone.css)
    const onPhone = document.body.classList.contains('phone-shell');
    if (onPhone || localStorage.getItem('zettnas_ai_sidebar_collapsed') === '1') {
      const sidebar = document.getElementById('ai-chat-sidebar');
      if (sidebar) sidebar.classList.add('collapsed');
      if (btnOpen) btnOpen.style.display = 'flex';
    }
  } catch (_) {}

  fetchAndRenderAiConversations().catch(() => {});
}

let _aiChatHistory = [];

export function isAiThinkingModel(modelName) {
  const m = String(modelName || '').toLowerCase();
  return m.includes('r1') ||
         m.includes('qwq') ||
         m.includes('reason') ||
         m.includes('thinking') ||
         m.includes('saluki') ||
         m.includes('cot') ||
         m.includes('deepseek');
}

// One citation style: [n] points at a web source when the answer has any, else at a document.
// Known numbers become chips that open the source; numbers with no source are dropped.
function _citationChip(n, sources) {
  const web = (sources && sources.webSources) || [];
  const docs = (sources && sources.citations) || [];
  const chip = 'display:inline-flex; align-items:center; font-size:11px; font-weight:700; color:#7dd3fc; background:rgba(56,189,248,0.16); border:1px solid rgba(56,189,248,0.35); border-radius:999px; padding:0 6px; margin:0 2px; vertical-align:baseline; line-height:1.3; cursor:pointer; text-decoration:none;';
  if (web.length) {
    const ws = web[n - 1];
    if (!ws || !/^https?:\/\//i.test(String(ws.url || ''))) return '';
    return `<a href="${escapeHtml(ws.url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(ws.title || ws.url)}" style="${chip}">[${n}]</a>`;
  }
  if (docs.length) {
    const c = docs[n - 1];
    if (!c) return '';
    const path = c.path || c.file_path || '';
    const name = c.name || (path ? path.split('/').pop() : 'Document');
    return `<button type="button" class="ai-citation-inline-pill" data-action="open-file-preview" data-path="${escapeHtml(path)}" data-name="${escapeHtml(name)}" title="${escapeHtml(name)}" style="${chip}">[${n}]</button>`;
  }
  return `<span style="${chip} cursor:default;">[${n}]</span>`;
}

export function _formatChatMarkdown(rawText, sources = null) {
  let text = String(rawText || '').replace(/\[(?:doc(?:ument)?|source)\s*(\d+)\]/gi, '[$1]');
  // Strip out any trailing verbose "Verified Web Sources" section
  text = text.replace(/#{2,4}\s*🌐?\s*Verified\s+Web\s+Sources[\s\S]*$/i, '').trim();
  // Strip out duplicate trailing text-based "Sources:\n[1] ... \n[2] ..." list
  text = text.replace(/(?:\r?\n)+\s*(?:\*\*)?Sources:?(?:\*\*)?\s*(?:\r?\n)+(?:\s*\[\d+\][^\n]*\r?\n?)+$/i, '').trim();

  // Extract <think>...</think> if present
  let thoughtHtml = '';
  const thinkMatch = text.match(/<think>([\s\S]*?)<\/think>/i);
  if (thinkMatch) {
    const thoughtContent = escapeHtml(thinkMatch[1].trim());
    text = text.replace(/<think>[\s\S]*?<\/think>/i, '').trim();
    thoughtHtml = `
      <details class="ai-thought-disclosure" style="margin: 4px 0 10px; border-radius: 8px; background: rgba(147, 51, 234, 0.08); border: 1px solid rgba(168, 85, 247, 0.28); padding: 7px 10px; font-size: 11px;">
        <summary style="cursor: pointer; font-weight: 700; color: var(--lt-t-c084fcff, #c084fc); display: inline-flex; align-items: center; gap: 6px; user-select: none;">
          <span>🧠 Thought Process</span>
          <span style="font-size: 11px; color: var(--lt-t-94a3b8ff, #94a3b8); font-weight: 400;">(click to view chain of thought)</span>
        </summary>
        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(168, 85, 247, 0.2); color: var(--lt-t-cbd5e1ff, #cbd5e1); font-size: 11px; line-height: 1.5; font-style: italic;">
          ${thoughtContent.replace(/\n/g, '<br/>')}
        </div>
      </details>
    `;
    if (!text.trim()) {
      text = '*(Thought process completed. No concluding response was emitted by the model.)*';
    }
  }

  // Handle fenced code blocks before escaping HTML
  const codeBlocks = [];
  text = text.replace(/```([a-zA-Z0-9_-]*)\r?\n([\s\S]*?)```/g, (match, lang, code) => {
    const idx = codeBlocks.length;
    const cleanLang = (lang || 'code').trim();
    codeBlocks.push({
      lang: cleanLang,
      code: code.trim(),
    });
    return `___CODE_BLOCK_${idx}___`;
  });

  let escaped = escapeHtml(text);

  // Restore code blocks with glassmorphic container and copy/deploy buttons
  escaped = escaped.replace(/___CODE_BLOCK_(\d+)___/g, (match, idxStr) => {
    const item = codeBlocks[parseInt(idxStr, 10)];
    if (!item) return match;
    const escapedCode = escapeHtml(item.code);
    const isComposeYaml =
      item.lang === 'yaml' ||
      item.lang === 'yml' ||
      item.lang === 'compose' ||
      item.lang === 'docker-compose' ||
      (item.code.includes('services:') && (item.code.includes('image:') || item.code.includes('build:') || item.code.includes('ports:')));

    const deployBtnHtml = isComposeYaml
      ? `<button type="button" class="btn-deploy-stack-code" data-action="deploy-compose-code" style="background: rgba(16, 185, 129, 0.22); border: 1px solid rgba(52, 211, 153, 0.45); border-radius: 4px; color: var(--lt-t-6ee7b7ff, #6ee7b7); font-size: 11px; font-weight: 700; padding: 2px 8px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; margin-right: 6px;">🚀 Deploy Stack</button>`
      : '';

    return `<div class="ai-chat-code-block" style="margin: 8px 0; border-radius: 8px; background: var(--lt-b-020617e0, rgba(2, 6, 23, 0.88)); border: 1px solid rgba(56, 189, 248, 0.3); overflow: hidden;">
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 4px 10px; background: var(--lt-b-0f172af2, rgba(15, 23, 42, 0.95)); border-bottom: 1px solid var(--lt-r-ffffff14, rgba(255, 255, 255, 0.08)); font-size: 11px; color: var(--lt-t-94a3b8ff, #94a3b8); font-family: monospace;">
        <span style="font-weight: 700; color: var(--lt-t-7dd3fcff, #7dd3fc);">${escapeHtml(item.lang)}</span>
        <div style="display: flex; align-items: center;">
          ${deployBtnHtml}
          <button type="button" class="btn-copy-code" data-action="copy-code" style="background: var(--lt-b-ffffff0f, rgba(255,255,255,0.06)); border: 1px solid var(--lt-r-ffffff2e, rgba(255,255,255,0.18)); border-radius: 4px; color: var(--lt-t-cbd5e1ff, #cbd5e1); font-size: 11px; padding: 2px 7px; cursor: pointer;">Copy</button>
        </div>
      </div>
      <pre style="margin: 0; padding: 10px 12px; overflow-x: auto; font-family: 'JetBrains Mono', Consolas, monospace; font-size: 11.5px; line-height: 1.5; color: var(--lt-t-e2e8f0ff, #e2e8f0);"><code>${escapedCode}</code></pre>
    </div>`;
  });

  const formatted = escaped
    .replace(/^####\s+(.+)$/gm, '<div style="font-size:12px; font-weight:800; color:var(--lt-t-7dd3fcff, #7dd3fc); margin:8px 0 3px;">$1</div>')
    .replace(/^###\s+(.+)$/gm, '<div style="font-size:12.5px; font-weight:800; color:var(--lt-t-38bdf8ff, #38bdf8); margin:8px 0 4px;">$1</div>')
    .replace(/^&gt;\s?(.*)$/gm, '<div style="border-left:2px solid rgba(168,85,247,0.55); padding-left:8px; margin:3px 0; color:var(--lt-t-cbd5e1ff, #cbd5e1); font-size:11px; background:rgba(168,85,247,0.07); border-radius:0 4px 4px 0;">$1</div>')
    .replace(/^[-*]\s+(.+)$/gm, '<div style="display:flex; align-items:flex-start; gap:6px; margin:3px 0 3px 4px;"><span style="color:var(--lt-t-38bdf8ff, #38bdf8); font-size:11px; line-height:1.5;">•</span><div style="flex:1;">$1</div></div>')
    .replace(/^(\d+)\.\s+(.+)$/gm, '<div style="display:flex; align-items:flex-start; gap:6px; margin:3px 0 3px 4px;"><span style="color:var(--lt-t-c084fcff, #c084fc); font-weight:700; font-size:11px; line-height:1.5;">$1.</span><div style="flex:1;">$2</div></div>')
    .replace(/\*\*(.+?)\*\*/g, '<strong style="color:var(--lt-t-ffffffff, #fff);">$1</strong>')
    .replace(/`([^`]+)`/g, '<code style="background:var(--lt-b-00000061, rgba(0,0,0,0.38)); padding:1px 5px; border-radius:4px; color:var(--lt-t-bae6fdff, #bae6fd); font-family:monospace; font-size:11px;">$1</code>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" style="color:var(--lt-t-38bdf8ff, #38bdf8); text-decoration:underline;">$1 ↗</a>')
    .replace(/\[\^(\d+):\s*([^#\]]+)(?:#L?(\d+))?\]/g, (match, idx, path, line) => {
      const escP = escapeHtml(path.trim());
      const escN = escapeHtml(path.trim().split('/').pop() || 'File');
      const lineStr = line ? ` (L${line})` : '';
      return `<button type="button" class="ai-citation-inline-pill" data-action="open-file-preview" data-path="${escP}" data-name="${escN}" style="display:inline-flex; align-items:center; gap:3px; background:rgba(56,189,248,0.15); border:1px solid rgba(56,189,248,0.38); border-radius:999px; padding:1px 7px; color:var(--lt-t-7dd3fcff, #7dd3fc); font-size:11px; font-weight:700; cursor:pointer; vertical-align:baseline; margin:0 2px;"><span>📄 [${idx}] ${escN}${lineStr}</span><span style="font-size:11px;">👁️</span></button>`;
    })
    .replace(/\[(\d+)\](?!\()/g, (m, n) => _citationChip(Number(n), sources))
    .replace(/\n\n+/g, '<div style="height:6px;"></div>')
    .replace(/\n/g, '<br/>');

  return (thoughtHtml ? thoughtHtml : '') + formatted;
}

export function deployComposeStackSnippet(yamlCode) {
  if (!yamlCode) return;
  let deducedName = 'copilot-stack';
  const matchContainer = yamlCode.match(/container_name:\s*([a-zA-Z0-9_-]+)/);
  if (matchContainer && matchContainer[1]) {
    deducedName = matchContainer[1];
  } else {
    const matchService = yamlCode.match(/services:\s*\r?\n\s+([a-zA-Z0-9_-]+):/);
    if (matchService && matchService[1]) {
      deducedName = matchService[1];
    }
  }
  openStackModal(deducedName, yamlCode);
  showToast(t('docker.stack_template_loaded', 'Stack template loaded into Compose editor.'), 'success');
}

if (typeof window !== 'undefined') {
  window.deployComposeStackSnippet = deployComposeStackSnippet;
}

export function clearAiChatHistory() {
  _aiChatHistory = [];
  const listEl = document.getElementById('ai-chat-messages-list');
  if (!listEl) return;
  listEl.innerHTML = '';
}

/** Stops the answer being generated; the server stops the model when the stream closes (AI-12). */
export function stopAiChatGeneration() {
  if (!_aiActiveAbortController) return false;
  _aiStopRequested = true;
  _aiActiveAbortController.abort();
  _aiActiveAbortController = null;
  return true;
}

export async function sendAiChatMessage(rawMessage = null) {
  const inputEl = document.getElementById('ai-chat-input');
  const sendBtn = document.getElementById('btn-ai-chat-send');
  const listEl = document.getElementById('ai-chat-messages-list');

  const msg = (rawMessage !== null && rawMessage !== undefined ? String(rawMessage) : (inputEl ? inputEl.value : '')).trim();
  if (!msg) {
    showToast(t('ai.enter_question', 'Please enter a question or command for the NAS Copilot.'), 'warn');
    return null;
  }

  if (inputEl) inputEl.value = '';
  if (sendBtn) {
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<span><span class="ai-typing-dot" style="width:5px;height:5px;margin-right:3px;"></span></span> <span>Generating...</span>';
  }

  // Web search and weather send the question outside the NAS: only when the user turns it on (AI-06).
  const allowWeb = !!document.getElementById('ai-chat-web-toggle')?.checked;
  const allowTools = true;
  const activeModel = _aiLastActiveModel || '—';
  const isThinking = isAiThinkingModel(activeModel);
  let streamBotMsgEl = null;

  if (listEl) {
    const userMsgEl = document.createElement('div');
    userMsgEl.className = 'ai-chat-msg ai-chat-msg-user';
    userMsgEl.style.cssText = 'align-self: flex-end; max-width: 85%; padding: 9px 13px; border-radius: 10px; background: rgba(14, 165, 233, 0.22); border: 1px solid rgba(56, 189, 248, 0.45); color: #f8fafc; font-size: 12px; line-height: 1.45;';
    userMsgEl.innerHTML = `<div style="font-size:11px; font-weight:700; color:var(--lt-t-7dd3fcff, #7dd3fc); margin-bottom:3px;">🧑 You</div><div>${escapeHtml(msg)}</div>`;
    listEl.appendChild(userMsgEl);

    const pendingEl = document.createElement('div');
    pendingEl.className = 'ai-chat-msg ai-chat-msg-pending';
    pendingEl.dataset.isThinking = isThinking ? '1' : '0';
    if (isThinking) {
      pendingEl.style.cssText = 'align-self: flex-start; max-width: 85%; padding: 10px 14px; border-radius: 10px; background: rgba(30, 20, 50, 0.75); border: 1px solid rgba(192, 132, 252, 0.4); display: flex; align-items: center; gap: 8px; box-shadow: 0 4px 14px rgba(168, 85, 247, 0.15);';
      pendingEl.innerHTML = `
        <span class="ai-thinking-brain" style="font-size: 15px;">🧠</span>
        <span style="font-size: 12px; font-weight: 700; color: var(--lt-t-e9d5ffff, #e9d5ff);">Thinking</span>
        <span class="ai-thinking-dots" style="color: var(--lt-t-c084fcff, #c084fc); font-weight: 800; letter-spacing: 2px;">
          <span class="ai-dot-1">.</span><span class="ai-dot-2">.</span><span class="ai-dot-3">.</span>
        </span>
        <span style="font-size: 11px; color: var(--lt-t-d8b4feff, #d8b4fe); margin-left: 6px; padding: 1px 7px; border-radius: 999px; background: rgba(168, 85, 247, 0.2); border: 1px solid rgba(192, 132, 252, 0.35);">${escapeHtml(activeModel)}</span>
      `;
    } else {
      pendingEl.style.cssText = 'align-self: flex-start; max-width: 85%; padding: 10px 14px; border-radius: 10px; background: rgba(15, 23, 42, 0.75); border: 1px solid rgba(56, 189, 248, 0.35); display: flex; align-items: center; gap: 9px; box-shadow: 0 4px 14px rgba(14, 165, 233, 0.12);';
      pendingEl.innerHTML = `
        <div class="ai-typing-indicator" style="display: inline-flex; align-items: center; gap: 4px;">
          <span class="ai-typing-dot"></span>
          <span class="ai-typing-dot"></span>
          <span class="ai-typing-dot"></span>
        </div>
        <span style="font-size: 11px; color: var(--lt-t-cbd5e1ff, #cbd5e1);">Processing with <strong style="color: var(--lt-t-38bdf8ff, #38bdf8);">${escapeHtml(activeModel)}</strong>...</span>
      `;
    }
    listEl.appendChild(pendingEl);
    listEl.scrollTop = listEl.scrollHeight;
  }


  try {
    const isTestEnv = window.__forceAiStreamingTest
      ? false
      : (typeof vi !== 'undefined' ||
         typeof vitest !== 'undefined' ||
         (typeof process !== 'undefined' && process?.env?.NODE_ENV === 'test') ||
         typeof window === 'undefined' ||
         !window.fetch ||
         !window.ReadableStream);

    let res = null;

    if (isTestEnv) {
      res = await api.post('/api/media/chat', {
        message: msg,
        history: _aiChatHistory.slice(-10),
        allow_web_search: allowWeb,
        allow_nas_tools: allowTools,
        conversation_id: _activeConversationId,
      });
      if (res && res.conversation_title && _activeConversationId) {
        _activeConversationTitle = res.conversation_title;
        const titleEl = document.getElementById('ai-chat-active-title');
        if (titleEl) titleEl.textContent = res.conversation_title;
      }
    } else {
      // Production browser runtime: consume SSE stream from /api/media/chat/stream
      let partialReply = '';
      let partialTools = [];
      const stopBtn = document.getElementById('btn-ai-chat-stop');
      _aiStopRequested = false;
      try {
        if (stopBtn) stopBtn.hidden = false;
        const streamHeaders = {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        };
        const token = auth.getToken();
        if (token) streamHeaders['Authorization'] = `Bearer ${token}`;

        if (_aiActiveAbortController) {
          _aiActiveAbortController.abort();
          _aiActiveAbortController = null;
        }
        _aiActiveAbortController = new AbortController();
        const currentConvId = _activeConversationId;
        const currentReqId = ++_aiActiveRequestId;

        const streamRes = await window.fetch('/api/media/chat/stream', {
          method: 'POST',
          headers: streamHeaders,
          body: JSON.stringify({
            message: msg,
            history: _aiChatHistory.slice(-10),
            allow_web_search: allowWeb,
            allow_nas_tools: allowTools,
            conversation_id: currentConvId,
          }),
          signal: _aiActiveAbortController.signal,
        });

        if (!streamRes.ok) {
          throw new Error(`HTTP ${streamRes.status}`);
        }

        const reader = streamRes.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let streamBuffer = '';
        let currentEvent = 'message';
        let donePayload = null;
        let toolsCollected = [];
        let streamedThinking = '';
        let streamedTokens = '';

        streamBotMsgEl = null;
        let replyBodyEl = null;
        let thoughtDetailsEl = null;
        let thoughtBodyEl = null;
        let toolsTraceEl = null;

        const setupStreamBotEl = () => {
          if (streamBotMsgEl || !listEl) return;
          const pending = listEl.querySelector('.ai-chat-msg-pending');
          if (pending) pending.remove();

          streamBotMsgEl = document.createElement('div');
          streamBotMsgEl.className = 'ai-chat-msg ai-chat-msg-assistant';
          if (currentConvId) streamBotMsgEl.dataset.convId = currentConvId;
          streamBotMsgEl.dataset.activeModel = activeModel;
          streamBotMsgEl.dataset.isStreaming = '1';
          streamBotMsgEl.style.cssText = 'display: flex; flex-direction: column; gap: 7px; padding: 11px 14px; border-radius: 10px; background: rgba(15, 23, 42, 0.78); border: 1px solid rgba(56, 189, 248, 0.28);';

          streamBotMsgEl.innerHTML = `
            <div class="ai-chat-llm-proof-bar" style="display: flex; justify-content: space-between; align-items: center; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid var(--lt-r-ffffff0f, rgba(255,255,255,0.06)); padding-bottom: 5px;">
              <div style="display: flex; align-items: center; gap: 6px;">
                <span class="ai-chat-model-pill" style="font-size: 11px; font-weight: 800; color: var(--lt-t-e9d5ffff, #e9d5ff); padding: 1px 8px; border-radius: 999px; background: rgba(168,85,247,0.18); border: 1px solid rgba(192,132,252,0.45);">🤖 ${escapeHtml(activeModel)}</span>
                <span style="font-size: 11px; font-weight: 700; color: var(--lt-t-38bdf8ff, #38bdf8); display: inline-flex; align-items: center; gap: 4px;">
                  <span class="ai-typing-dot" style="width: 5px; height: 5px;"></span> Streaming
                </span>
              </div>
            </div>
            <div class="ai-chat-tools-trace" style="display: flex; flex-wrap: wrap; gap: 5px; padding-top: 2px;"></div>
            <div class="ai-chat-reply-body" style="font-size: 12px; color: var(--lt-t-f1f5f9ff, #f1f5f9); line-height: 1.55;"></div>
          `;
          listEl.appendChild(streamBotMsgEl);
          toolsTraceEl = streamBotMsgEl.querySelector('.ai-chat-tools-trace');
          replyBodyEl = streamBotMsgEl.querySelector('.ai-chat-reply-body');
          listEl.scrollTop = listEl.scrollHeight;
        };

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          streamBuffer += decoder.decode(value, { stream: true });
          const lines = streamBuffer.split(/\r?\n/);
          streamBuffer = lines.pop();

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) {
              currentEvent = 'message';
              continue;
            }
            if (trimmed.startsWith('event:')) {
              currentEvent = trimmed.slice(6).trim();
              continue;
            }
            if (trimmed.startsWith('data:')) {
              const dataStr = trimmed.slice(5).trim();
              let parsed = null;
              try { parsed = JSON.parse(dataStr); } catch (_) { parsed = dataStr; }

              if (currentConvId && (_activeConversationId !== currentConvId || _aiActiveRequestId !== currentReqId)) {
                try { reader.cancel(); } catch (_) {}
                return null;
              }

              if (currentEvent === 'conversation_title') {
                if (parsed?.title && currentConvId === _activeConversationId) {
                  _activeConversationTitle = parsed.title;
                  const titleEl = document.getElementById('ai-chat-active-title');
                  if (titleEl) titleEl.textContent = parsed.title;
                  const tItem = document.querySelector(`.ai-thread-item[data-conv-id="${currentConvId}"] .ai-thread-title-text`);
                  if (tItem) tItem.textContent = parsed.title;
                }
              } else if (currentEvent === 'tool_start') {
                setupStreamBotEl();
                const toolName = parsed?.tool || 'tool';
                if (toolsTraceEl) {
                  const pill = document.createElement('span');
                  pill.className = 'ai-chat-tool-pill ai-chat-tool-running';
                  pill.dataset.toolName = toolName;
                  pill.style.cssText = 'font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: rgba(56,189,248,0.16); border: 1px solid rgba(56,189,248,0.42); color: #7dd3fc;';
                  pill.textContent = `⚡ Running ${toolName}...`;
                  toolsTraceEl.appendChild(pill);
                }
              } else if (currentEvent === 'tool_done') {
                setupStreamBotEl();
                toolsCollected.push(parsed);
                partialTools = toolsCollected;
                if (toolsTraceEl) {
                  const existingPill = toolsTraceEl.querySelector(`.ai-chat-tool-pill[data-tool-name="${parsed?.tool}"]`);
                  const isWeb = parsed?.tool === 'browse_internet';
                  const isRag = parsed?.tool === 'search_nas_knowledge';
                  const isCalc = parsed?.tool === 'calculate';
                  const isStorage = parsed?.tool === 'get_storage_status';
                  const isNet = parsed?.tool === 'get_network_status';
                  const isWeather = parsed?.tool === 'get_weather';
                  const bg = isCalc ? 'rgba(245,158,11,0.16)' : (isWeather ? 'rgba(14,165,233,0.18)' : (isWeb ? 'rgba(56,189,248,0.16)' : (isRag ? 'rgba(168,85,247,0.16)' : (isNet ? 'rgba(14,165,233,0.16)' : 'rgba(16,185,129,0.16)'))));
                  const border = isCalc ? 'rgba(251,191,36,0.42)' : (isWeather ? 'rgba(56,189,248,0.45)' : (isWeb ? 'rgba(56,189,248,0.42)' : (isRag ? 'rgba(168,85,247,0.42)' : (isNet ? 'rgba(56,189,248,0.42)' : 'rgba(52,211,153,0.42)'))));
                  const color = isCalc ? '#fde68a' : (isWeather ? '#38bdf8' : (isWeb ? '#7dd3fc' : (isRag ? '#d8b4fe' : (isNet ? '#7dd3fc' : '#6ee7b7'))));
                  const icon = isCalc ? '🧮' : (isWeather ? '⛅' : (isWeb ? '🌐' : (isRag ? '📁' : (isStorage ? '💽' : (isNet ? '🔌' : '🛠️')))));
                  const pillHtml = `${icon} ${escapeHtml(parsed?.tool || 'tool')}: ${escapeHtml(parsed?.summary || 'OK')}`;
                  if (existingPill) {
                    existingPill.className = 'ai-chat-tool-pill';
                    existingPill.style.background = bg;
                    existingPill.style.border = `1px solid ${border}`;
                    existingPill.style.color = color;
                    existingPill.innerHTML = pillHtml;
                  } else {
                    const newPill = document.createElement('span');
                    newPill.className = 'ai-chat-tool-pill';
                    newPill.dataset.toolName = parsed?.tool || 'tool';
                    newPill.style.cssText = `font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: ${bg}; border: 1px solid ${border}; color: ${color};`;
                    newPill.innerHTML = pillHtml;
                    toolsTraceEl.appendChild(newPill);
                  }
                }
              } else if (currentEvent === 'think') {
                setupStreamBotEl();
                const tok = parsed?.token || '';
                streamedThinking += tok;
                if (!thoughtDetailsEl && streamBotMsgEl) {
                  thoughtDetailsEl = document.createElement('details');
                  thoughtDetailsEl.className = 'ai-thought-disclosure';
                  thoughtDetailsEl.open = true;
                  thoughtDetailsEl.style.cssText = 'margin: 4px 0 10px; border-radius: 8px; background: rgba(147, 51, 234, 0.08); border: 1px solid rgba(168, 85, 247, 0.28); padding: 7px 10px; font-size: 11px;';
                  thoughtDetailsEl.innerHTML = `
                    <summary style="cursor: pointer; font-weight: 700; color: var(--lt-t-c084fcff, #c084fc); display: inline-flex; align-items: center; gap: 6px; user-select: none;">
                      <span>🧠 Thought Process</span>
                      <span style="font-size: 11px; color: var(--lt-t-94a3b8ff, #94a3b8); font-weight: 400;">(reasoning in real time...)</span>
                    </summary>
                    <div class="ai-thought-content" style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(168, 85, 247, 0.2); color: var(--lt-t-cbd5e1ff, #cbd5e1); font-size: 11px; line-height: 1.5; font-style: italic;"></div>
                  `;
                  if (replyBodyEl) streamBotMsgEl.insertBefore(thoughtDetailsEl, replyBodyEl);
                  thoughtBodyEl = thoughtDetailsEl.querySelector('.ai-thought-content');
                }
                if (thoughtBodyEl) {
                  thoughtBodyEl.innerHTML = escapeHtml(streamedThinking).replace(/\n/g, '<br/>');
                }
                listEl.scrollTop = listEl.scrollHeight;
              } else if (currentEvent === 'reset') {
                // The model chose to use tools: what it streamed so far wasn't the answer.
                streamedTokens = '';
                partialReply = '';
                if (replyBodyEl) replyBodyEl.innerHTML = '';
              } else if (currentEvent === 'token') {
                setupStreamBotEl();
                const tok = parsed?.token || '';
                streamedTokens += tok;
                partialReply = streamedTokens;
                if (replyBodyEl) {
                  replyBodyEl.innerHTML = _formatChatMarkdown(streamedTokens);
                }
                listEl.scrollTop = listEl.scrollHeight;
              } else if (currentEvent === 'done') {
                donePayload = parsed;
              } else if (currentEvent === 'error') {
                throw new Error(parsed?.error || 'Streaming error');
              }
            }
          }
        }

        if (donePayload) {
          res = donePayload;
          if (streamBotMsgEl) {
            delete streamBotMsgEl.dataset.isStreaming;
            streamBotMsgEl.innerHTML = _buildAiAssistantMessageHtml(res, activeModel);
          }
        } else if (streamedTokens) {
          res = {
            status: 'ok',
            reply: streamedTokens,
            tools_called: toolsCollected,
            active_model: activeModel,
          };
        }
      } catch (streamErr) {
        if (streamErr && streamErr.name === 'AbortError') {
          // Stopped by the user (or replaced by a newer request): never re-send the question.
          if (!_aiStopRequested) return null;
          res = {
            status: 'ok',
            stopped: true,
            reply: `${partialReply}${partialReply ? '\n\n' : ''}_${t('ai.stopped', 'Stopped.')}_`,
            tools_called: partialTools,
            active_model: activeModel,
          };
          if (streamBotMsgEl) {
            delete streamBotMsgEl.dataset.isStreaming;
            streamBotMsgEl.innerHTML = _buildAiAssistantMessageHtml(res, activeModel);
          }
        } else {
        console.warn('[ZettAI] Streaming fell back to standard POST:', streamErr);
        if (streamBotMsgEl) {
          streamBotMsgEl.remove();
          streamBotMsgEl = null;
        }
        res = await api.post('/api/media/chat', {
          message: msg,
          history: _aiChatHistory.slice(-10),
          allow_web_search: allowWeb,
          allow_nas_tools: allowTools,
          conversation_id: _activeConversationId,
        });
        }
      } finally {
        if (stopBtn) stopBtn.hidden = true;
      }
    }

    if (listEl) {
      const pending = listEl.querySelector('.ai-chat-msg-pending');
      if (pending) pending.remove();
    }

    if (!res) return null;

    const replyMd = res.reply || res.answer || 'No response generated.';
    const llmTel = res.llm_telemetry || {};
    const usedModel = llmTel.active_model || res.active_model || activeModel;

    _aiChatHistory.push({ role: 'user', content: msg });
    _aiChatHistory.push({ role: 'assistant', content: replyMd });

    if (listEl) {
      if (streamBotMsgEl) {
        // Streamed message bubble was already created and populated in listEl during the stream.
        // Update model and conversation tracking dataset attributes without appending a duplicate element!
        streamBotMsgEl.dataset.activeModel = usedModel;
        if (_activeConversationId) streamBotMsgEl.dataset.convId = _activeConversationId;
      } else {
        // Non-streaming fallback (e.g. test environment or network fallback where streaming was bypassed)
        const botMsgEl = document.createElement('div');
        botMsgEl.className = 'ai-chat-msg ai-chat-msg-assistant';
        botMsgEl.dataset.activeModel = usedModel;
        if (_activeConversationId) botMsgEl.dataset.convId = _activeConversationId;
        botMsgEl.style.cssText = 'display: flex; flex-direction: column; gap: 7px; padding: 11px 14px; border-radius: 10px; background: rgba(15, 23, 42, 0.78); border: 1px solid rgba(56, 189, 248, 0.28);';
        botMsgEl.innerHTML = _buildAiAssistantMessageHtml(res, activeModel);
        listEl.appendChild(botMsgEl);
      }
      listEl.scrollTop = listEl.scrollHeight;
    }

    return res;
  } catch (err) {
    if (listEl) {
      const pending = listEl.querySelector('.ai-chat-msg-pending');
      if (pending) pending.remove();
      const errEl = document.createElement('div');
      errEl.className = 'ai-chat-msg ai-chat-msg-error';
      errEl.style.cssText = 'padding: 10px 14px; border-radius: 10px; background: rgba(239, 68, 68, 0.14); border: 1px solid rgba(248, 113, 113, 0.45); color: #fecaca; font-size: 12px;';
      errEl.textContent = `⚠️ Chatbot error: ${err.message || String(err)}`;
      listEl.appendChild(errEl);
      listEl.scrollTop = listEl.scrollHeight;
    }
    return null;
  } finally {
    if (sendBtn) {
      sendBtn.disabled = false;
      sendBtn.innerHTML = `<span aria-hidden="true">🚀</span> <span data-i18n="ai.chat_send_btn">${escapeHtml(t('ai.chat_send_btn', 'Ask Zetty'))}</span>`;
    }
  }
}

export function updateAiReindexProgress(data) {
  const container = document.getElementById('ai-reindex-progress-container');
  const topBanner = document.getElementById('ai-reindex-top-banner');
  const univStrip = document.getElementById('ai-reindex-universal-strip');
  const sidebarBadge = document.getElementById('mgmt-sidebar-ai-badge');
  const topText = document.getElementById('topbar-ai-accel-text');

  if (!data || data.status === 'idle' || data.type === 'complete' || (data.total > 0 && data.completed >= data.total)) {
    if (container) container.style.display = 'none';
    if (topBanner) topBanner.style.display = 'none';
    if (univStrip) univStrip.style.display = 'none';
    if (sidebarBadge && sidebarBadge.dataset.reindexing) {
      sidebarBadge.textContent = 'NPU/GPU';
      sidebarBadge.style.background = 'rgba(14,165,233,0.18)';
      sidebarBadge.style.color = 'var(--accent-cyan,#00f0ff)';
      delete sidebarBadge.dataset.reindexing;
    }
    return;
  }

  const pct = data.percentage ?? (data.total > 0 ? Math.round((data.completed / data.total) * 100) : 0);
  const completed = data.completed ?? 0;
  const total = data.total ?? 0;
  const speed = data.speed !== undefined ? data.speed : 0;
  const etaSec = data.eta_sec !== undefined ? data.eta_sec : 0;

  let etaText = 'ETA: --';
  if (etaSec > 0) {
    if (etaSec < 60) {
      etaText = `ETA: ${Math.round(etaSec)}s`;
    } else if (etaSec < 3600) {
      const mins = Math.floor(etaSec / 60);
      const secs = Math.round(etaSec % 60);
      etaText = `ETA: ${mins}m ${secs}s`;
    } else {
      const hrs = Math.floor(etaSec / 3600);
      const mins = Math.round((etaSec % 3600) / 60);
      etaText = `ETA: ${hrs}h ${mins}m`;
    }
  }

  if (sidebarBadge) {
    sidebarBadge.dataset.reindexing = '1';
    sidebarBadge.textContent = `${pct}% Re-index`;
    sidebarBadge.style.background = 'rgba(234, 179, 8, 0.2)';
    sidebarBadge.style.color = '#fbbf24';
  }

  if (topText) {
    topText.textContent = `Re-indexing ${pct}% • ${etaText}`;
  }

  // Update top banner
  if (topBanner) {
    topBanner.style.display = 'block';
    const topBar = document.getElementById('ai-reindex-top-progress-bar');
    if (topBar) topBar.style.width = `${pct}%`;
    const topPct = document.getElementById('ai-reindex-top-pct-label');
    if (topPct) topPct.textContent = `${pct}%`;
    const topChunks = document.getElementById('ai-reindex-top-chunks-label');
    if (topChunks) topChunks.textContent = `${formatNumber(completed)} / ${formatNumber(total)} chunks`;
    const topSpeed = document.getElementById('ai-reindex-top-speed-label');
    if (topSpeed) topSpeed.textContent = `${speed} chunks/s`;
    const topEta = document.getElementById('ai-reindex-top-eta-label');
    if (topEta) topEta.textContent = etaText;
  }

  // Update universal strip (visible across all tabs: Chatbot, RAG, Configuration)
  if (univStrip) {
    univStrip.style.display = 'block';
    const uBar = document.getElementById('ai-reindex-univ-bar');
    if (uBar) uBar.style.width = `${pct}%`;
    const uPct = document.getElementById('ai-reindex-univ-pct');
    if (uPct) uPct.textContent = `${pct}%`;
    const uChunks = document.getElementById('ai-reindex-univ-chunks');
    if (uChunks) uChunks.textContent = `${formatNumber(completed)} / ${formatNumber(total)} chunks`;
    const uSpeed = document.getElementById('ai-reindex-univ-speed');
    if (uSpeed) uSpeed.textContent = `${speed} chunks/s`;
    const uEta = document.getElementById('ai-reindex-univ-eta');
    if (uEta) uEta.textContent = etaText;
  }

  // Update bottom container in MRL card
  if (container) {
    container.style.display = 'block';
    const bar = document.getElementById('ai-reindex-progress-bar');
    if (bar) bar.style.width = `${pct}%`;
    const pctLabel = document.getElementById('ai-reindex-pct-label');
    if (pctLabel) pctLabel.textContent = `${pct}%`;
    const speedLabel = document.getElementById('ai-reindex-speed-label');
    if (speedLabel) speedLabel.textContent = `${speed} chunks/s`;
    const etaLabel = document.getElementById('ai-reindex-eta-label');
    if (etaLabel) etaLabel.textContent = etaText;
  }
}

let _reindexPollTimer = null;
export function _pollReindexProgress() {
  if (_reindexPollTimer) return;
  _reindexPollTimer = setInterval(async () => {
    try {
      const st = await api.get('/api/ai/reindex/status');
      if (st) {
        updateAiReindexProgress(st);
        if (st.status !== 'running') {
          clearInterval(_reindexPollTimer);
          _reindexPollTimer = null;
          if (st.percentage >= 100 || (st.total > 0 && st.completed >= st.total)) {
            showToast(t('ai.reindex_completed', '✓ In-place re-indexing completed successfully!'), 'success');
          }
        }
      }
    } catch {
      clearInterval(_reindexPollTimer);
      _reindexPollTimer = null;
    }
  }, 1500);
}

export async function triggerInPlaceReindex() {
  const container = document.getElementById('ai-reindex-progress-container');
  if (container) container.style.display = 'block';
  try {
    const resp = await api.post('/api/ai/reindex');
    if (resp && (resp.status === 'ok' || resp.status === 'in_progress')) {
      showToast(t('ai.reindex_started', 'In-place re-indexing started in background'), 'success');
      _pollReindexProgress();
    }
  } catch (err) {
    showToast(t('toast.failed_trigger_reindex', 'Failed to start re-indexing: {error}', { error: err.message }), 'error');
  }
}



/** Shows how many photos the vision model has described (AI-14). */
export async function refreshVisionStatus() {
  const el = document.getElementById('ai-vision-status');
  if (!el) return;
  try {
    const st = await api.get('/api/ai/vision/status');
    if (st.mode === 'off') {
      el.textContent = '';
    } else if (st.state === 'no-model') {
      el.textContent = t('ai.vision_no_model', 'Install a vision model (for example gemma3 or qwen2.5vl) under AI → Models.');
    } else {
      el.textContent = t('ai.vision_progress', '{done} of {total} photos described', { done: st.captioned, total: st.photos });
    }
  } catch {
    el.textContent = '';
  }
}


/** After Tailscale Serve is on: the address to open on a phone, with a QR code (M2). */
export async function showServeLink(url, funnel = false) {
  let qr = '';
  try {
    const { default: QRCode } = await import('qrcode');
    qr = await QRCode.toDataURL(url, { margin: 1, width: 180 });
  } catch (e) {
    console.warn('QR code unavailable', e);
  }
  const how = funnel
    ? t('ts.serve_how_funnel', 'Funnel is on: this address works from any browser on the internet, so keep strong passwords and 2FA.')
    : t('ts.serve_how', 'On your phone, install the Tailscale app and sign in to the same tailnet. Then open this address, on Wi-Fi or mobile data. Add it to your home screen to use ZettNAS like an app.');
  showConfirmToast(
    t('ts.serve_ready', 'ZettNAS is reachable through Tailscale'),
    `${qr ? `<img src="${qr}" alt="${escapeHtml(t('ts.serve_qr_alt', 'QR code for {url}', { url }))}" width="180" height="180" style="display:block;margin:0 auto 10px;border-radius:8px;background:#fff;">` : ''}<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" style="color:var(--lt-t-38bdf8ff, #38bdf8);font-weight:700;word-break:break-all;">${escapeHtml(url)}</a><br><br>${escapeHtml(how)}`,
    () => {
      copyText(url).catch(() => {});
    },
    null,
    { confirmText: t('ts.serve_copy', 'Copy address'), cancelText: t('common.close', 'Close'), allowHtml: true }
  );
}
