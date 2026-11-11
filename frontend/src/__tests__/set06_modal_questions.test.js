/** SET-06: a question asked from a native modal window is drawn inside it, where it can be answered. */
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { showConfirmToast, showPromptToast, hideConfirmToast } from '../toast.js';

/** A window as the snapshot browser opens it: modal. The test browser has no showModal(), so the
 *  window only says it is modal here; a real browser proves the rest (tests/test_e2e_journeys.py). */
function modalWindow() {
  const dlg = document.createElement('dialog');
  dlg.setAttribute('open', '');
  const matches = dlg.matches.bind(dlg);
  dlg.matches = (sel) => (sel === ':modal' ? dlg.hasAttribute('open') : matches(sel));
  dlg.close = () => dlg.removeAttribute('open');
  document.body.appendChild(dlg);
  return dlg;
}

const tokens = readFileSync(resolve(__dirname, '..', 'styles/00-tokens.css'), 'utf8');

describe('questions and native modal windows (SET-06)', () => {
  beforeEach(() => {
    hideConfirmToast();
    document.body.innerHTML = '';
  });

  it('a window that is open but not modal leaves the question in the page', () => {
    const dlg = document.createElement('dialog');
    dlg.setAttribute('open', '');
    document.body.appendChild(dlg);
    showConfirmToast('Delete?', 'Sure?', () => {});
    expect(document.getElementById('confirm-toast-modal').parentNode).toBe(document.body);
  });

  it('with no window open the question is in the page, as before', () => {
    showConfirmToast('Delete?', 'Sure?', () => {});
    expect(document.getElementById('confirm-toast-modal').parentNode).toBe(document.body);
    expect(document.getElementById('confirm-toast-backdrop').parentNode).toBe(document.body);
  });

  it('with a window open the question goes into it, and comes back out afterwards', () => {
    showConfirmToast('First', 'In the page', () => {});
    hideConfirmToast();
    const dlg = modalWindow();
    showConfirmToast('Replace?', 'Replace the current file?', () => {});
    expect(document.getElementById('confirm-toast-modal').parentNode).toBe(dlg);
    expect(document.getElementById('confirm-toast-backdrop').parentNode).toBe(dlg);
    hideConfirmToast();
    dlg.close();
    showConfirmToast('Later', 'In the page again', () => {});
    expect(document.getElementById('confirm-toast-modal').parentNode).toBe(document.body);
  });

  it('a question that asks for a word does the same', () => {
    const dlg = modalWindow();
    showPromptToast('Name', 'Type a name', '', () => {});
    expect(document.getElementById('confirm-toast-modal').parentNode).toBe(dlg);
  });

  it('the newest open window is the one', () => {
    modalWindow();
    const b = modalWindow();
    showConfirmToast('Sure?', 'Really?', () => {});
    expect(document.getElementById('confirm-toast-modal').parentNode).toBe(b);
  });

  it('native dialogs get back the margin that centres them', () => {
    expect(tokens).toMatch(/\*\{box-sizing:border-box;margin:0;padding:0\}\n\/\*[^]*?\*\/\ndialog\{margin:auto\}/);
  });
});
