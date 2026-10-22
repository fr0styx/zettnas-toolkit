/**
 * Delegated handlers that replace inline on*="" attributes, so the page works under a
 * Content-Security-Policy without 'unsafe-inline' scripts (FE-06).
 *
 *   data-action="click-target"  data-target="id"   click another element
 *   data-action="hide-target"   data-target="id"   hide an element
 *   data-action="open-recycle-bin"
 *   data-action="open-file-preview" data-path="…" data-name="…"
 *   data-action="deploy-compose-code" / "copy-code"  (inside .ai-chat-code-block)
 *   <img data-img-fallback="url">        swap to url once if loading fails
 *   <img data-img-fallback="hide">       hide on error
 *   <img data-img-fallback="hide-show-next[:display]">  hide, show the next sibling
 */
import { copyText } from './utils.js';
const ACTIONS = {
  'click-target': (el) => document.getElementById(el.dataset.target)?.click(),
  'hide-target': (el) => {
    const t = document.getElementById(el.dataset.target);
    if (t) t.style.display = 'none';
  },
  'open-recycle-bin': () => window.openRecycleBin && window.openRecycleBin(),
  'open-file-preview': (el) => window.openFilePreviewModal && window.openFilePreviewModal(el.dataset.path || '', el.dataset.name || ''),
  'deploy-compose-code': (el) => {
    const code = el.closest('.ai-chat-code-block')?.querySelector('code')?.innerText;
    if (code && window.deployComposeStackSnippet) window.deployComposeStackSnippet(code);
  },
  'copy-code': (el) => {
    const code = el.closest('.ai-chat-code-block')?.querySelector('code')?.innerText || '';
    const label = el.textContent;
    copyText(code).then(() => {
      el.textContent = '✓';
      setTimeout(() => {
        el.textContent = label;
      }, 1600);
    });
  },
};

function onClick(e) {
  const el = e.target.closest?.('[data-action]');
  if (!el || !ACTIONS[el.dataset.action]) return;
  ACTIONS[el.dataset.action](el, e);
}

function onKey(e) {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const el = e.target.closest?.('[data-action][role="button"]');
  if (!el || el.tagName === 'BUTTON' || !ACTIONS[el.dataset.action]) return;
  e.preventDefault();
  ACTIONS[el.dataset.action](el, e);
}

function onImgError(e) {
  const img = e.target;
  if (!(img instanceof HTMLImageElement) || !img.dataset.imgFallback) return;
  const rule = img.dataset.imgFallback;
  if (rule === 'hide') {
    img.style.display = 'none';
  } else if (rule.startsWith('hide-show-next')) {
    img.style.display = 'none';
    if (img.nextElementSibling) img.nextElementSibling.style.display = rule.split(':')[1] || 'inline';
  } else {
    delete img.dataset.imgFallback; // try the fallback once
    img.src = rule;
  }
}

let _installed = false;
export function installDomActions(root = document) {
  if (_installed) return;
  _installed = true;
  root.addEventListener('click', onClick);
  root.addEventListener('keydown', onKey);
  root.addEventListener('error', onImgError, true); // error doesn't bubble; capture it
}

export const _actionsForTesting = ACTIONS;
