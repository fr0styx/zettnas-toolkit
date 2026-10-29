/**
 * App Catalog cards, category chips and filtering, shared by Mission Control's catalog and the
 * Containers window. The server sends the templates (backend/services/catalog_templates.py).
 */
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';

/** Categories in display order: [id, translation key, English label, emoji] */
export const CATALOG_CATEGORIES = [
  ['media', 'catalog.cat_media', 'Media & Streaming', '🎬'],
  ['photos', 'catalog.cat_photos', 'Photos', '📸'],
  ['cloud', 'catalog.cat_cloud', 'Cloud & Files', '☁️'],
  ['productivity', 'catalog.cat_productivity', 'Productivity', '📝'],
  ['automation', 'catalog.cat_automation', 'Smart Home', '⚡'],
  ['network', 'catalog.cat_network', 'Network & Security', '🛡️'],
  ['monitoring', 'catalog.cat_monitoring', 'Monitoring', '📈'],
  ['downloads', 'catalog.cat_downloads', 'Downloads', '📥'],
  ['dev', 'catalog.cat_dev', 'Developer', '🧑‍💻'],
  ['ai', 'catalog.cat_ai', 'AI & Search', '🤖'],
  ['games', 'catalog.cat_games', 'Games', '🎮'],
  ['utilities', 'catalog.cat_utilities', 'Utilities', '🛠️'],
  ['other', 'catalog.cat_other', 'Other', '📦'],
];
const BY_ID = Object.fromEntries(CATALOG_CATEGORIES.map((c) => [c[0], c]));

export function categoryLabel(cat) {
  const c = BY_ID[cat] || BY_ID.other;
  return t(c[1], c[2]);
}

function categoryIcon(cat) {
  return (BY_ID[cat] || BY_ID.other)[3];
}

/** Image name without registry defaults or tag, for matching installed containers. */
export function imageRepo(image) {
  return String(image || '')
    .toLowerCase()
    .replace(/@sha256:[a-f0-9]+$/, '')
    .replace(/:[^/:]+$/, '')
    .replace(/^(docker\.io\/)?(library\/)?/, '');
}

/** True when a container on this host runs the app's image. */
export function isInstalled(app, containers) {
  const repo = imageRepo(app.image);
  if (!repo) return false;
  return (containers || []).some((c) => imageRepo(c.image || c.Image) === repo);
}

/** Apps matching a category and a search (name, description, image, tags, category, source). */
export function filterCatalog(apps, cat, query) {
  const q = String(query || '').trim().toLowerCase();
  return (apps || []).filter((app) => {
    if (cat && cat !== 'all' && (app.category || 'other') !== cat) return false;
    if (!q) return true;
    const hay = [app.name, app.description, app.id, app.image, app.source_name, categoryLabel(app.category), ...(app.tags || [])]
      .join(' ')
      .toLowerCase();
    return q.split(/\s+/).every((word) => hay.includes(word));
  });
}

/** Category chips with counts; only categories that have apps. */
export function catalogChipsHtml(apps, activeCat, chipClass, allCountId = '') {
  const counts = {};
  for (const app of apps || []) counts[app.category || 'other'] = (counts[app.category || 'other'] || 0) + 1;
  const chip = (id, label, n) =>
    `<button type="button" class="btn-pill-toggle ${chipClass} cat-chip${id === activeCat ? ' active' : ''}" data-cat="${id}" aria-pressed="${id === activeCat}">${escapeHtml(label)}<span class="cat-chip-count"${id === 'all' && allCountId ? ` id="${allCountId}"` : ''}>${n}</span></button>`;
  const parts = [chip('all', t('catalog.cat_all', 'All Apps'), (apps || []).length)];
  for (const [id] of CATALOG_CATEGORIES) {
    if (counts[id]) parts.push(chip(id, categoryLabel(id), counts[id]));
  }
  return parts.join('');
}

function badge(cls, text, title = '') {
  return `<span class="cat-badge ${cls}"${title ? ` title="${escapeHtml(title)}"` : ''}>${escapeHtml(text)}</span>`;
}

/** A logo from the web goes through ZettNAS, so the browser never asks a third party (SEC-38). */
export function logoSrc(url) {
  return /^https?:\/\//i.test(url || '') ? `/api/docker/catalog/logo?url=${encodeURIComponent(url)}` : url || '';
}

/** One app card. Keeps the .catalog-app-card / .btn-deploy-app hooks other code relies on. */
export function catalogCardHtml(app, { installed = false } = {}) {
  const icon = categoryIcon(app.category);
  const logo = app.logo
    ? `<img src="${escapeHtml(logoSrc(app.logo))}" alt="" loading="lazy" data-img-fallback="hide-show-next:inline" /><span class="cat-card-emoji" style="display:none;">${icon}</span>`
    : `<span class="cat-card-emoji">${icon}</span>`;
  const builtin = !app.source_name || app.source_name === 'Built-in';
  const badges = [badge('cat-badge-category', categoryLabel(app.category))];
  if (app.type === 'stack') badges.push(badge('cat-badge-stack', t('catalog.stack', 'Stack'), t('catalog.stack_hint', 'Installs several containers that work together')));
  if (builtin) {
    badges.push(badge('cat-badge-builtin', 'Built-in', t('catalog.builtin_hint', 'Tested ZettNAS template')));
  } else {
    badges.push(badge('cat-badge-source', app.source_name));
    if (app.security_rating === 'verified') badges.push(badge('cat-badge-ok', '🛡️ Safe', 'Verified Safe Sandbox'));
    else if (app.security_rating === 'review_required') badges.push(badge('cat-badge-warn', '⚠️ Review', (app.security_flags || []).join('; ')));
    else if (app.security_rating === 'elevated') badges.push(badge('cat-badge-crit', '🚨 Elevated', (app.security_flags || []).join('; ')));
  }
  if (installed) badges.push(badge('cat-badge-installed', `✓ ${t('catalog.installed', 'Installed')}`));
  const image = app.image || (app.repository ? 'compose-stack' : 'container');
  return `
    <div class="catalog-app-card${installed ? ' is-installed' : ''}" data-app-id="${escapeHtml(app.id)}">
      <div class="cat-card-head">
        <div class="cat-card-logo" aria-hidden="true">${logo}</div>
        <div class="cat-card-titles">
          <div class="cat-card-name" title="${escapeHtml(app.name)}">${escapeHtml(app.name)}</div>
          <code class="cat-card-image" title="${escapeHtml(image)}">${escapeHtml(image)}</code>
        </div>
      </div>
      <div class="cat-card-badges">${badges.join('')}</div>
      <p class="cat-card-desc">${escapeHtml(app.description || '')}</p>
      <div class="cat-card-foot">
        <span class="cat-card-port" title="${escapeHtml(t('catalog.port_hint', 'Suggested web UI port'))}">:${escapeHtml(String(app.default_port || ''))}</span>
        <button type="button" class="btn-pill-toggle btn-deploy-app catalog-deploy" data-appid="${escapeHtml(app.id)}">${escapeHtml(installed ? t('catalog.install_again', 'Install again') : t('catalog.install', 'Install'))}</button>
      </div>
    </div>`;
}

/** Wires chip clicks in a container; onPick(cat) re-renders. */
export function bindCatalogChips(container, chipSelector, onPick) {
  if (!container || container._catChipsBound) return;
  container._catChipsBound = true;
  container.addEventListener('click', (e) => {
    const btn = e.target instanceof Element ? e.target.closest(chipSelector) : null;
    if (!btn || !container.contains(btn)) return;
    container.querySelectorAll(chipSelector).forEach((b) => {
      b.classList.toggle('active', b === btn);
      b.setAttribute('aria-pressed', String(b === btn));
    });
    onPick(btn.dataset.cat || 'all');
  });
}
