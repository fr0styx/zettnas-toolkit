import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { iconizeTree, startIconizer, stopIconizer, stripEmoji, iconHtml, iconFor } from '../icons.js';
import EMOJI_ICONS from '../icons/emoji-icons.json';

const icons = (root) => [...root.querySelectorAll('svg.zi')].map((s) => s.dataset.zi);

describe('Emoji drawn as icons (UX-14)', () => {
  beforeEach(() => { document.body.innerHTML = ''; });
  afterEach(() => stopIconizer());

  it('replaces mapped emoji with sprite icons and keeps the text', () => {
    document.body.innerHTML = '<button id="b">💾 Save</button><p id="p">Warning ⚠️ hot</p>';
    iconizeTree(document.body);
    expect(icons(document.body)).toEqual(['save', 'triangle-alert']);
    expect(document.getElementById('b').textContent).toBe(' Save');
    expect(document.getElementById('p').textContent).toBe('Warning  hot');
    const svg = document.querySelector('svg.zi');
    expect(svg.getAttribute('aria-hidden')).toBe('true');
    expect(svg.querySelector('use').getAttribute('href')).toBe('/zi-sprite.svg#zi-save');
  });

  it('draws coloured circles as coloured dots', () => {
    document.body.innerHTML = '<span id="s">🟢 Online</span>';
    iconizeTree(document.body);
    expect(document.querySelector('.zi-dot-green')).not.toBeNull();
  });

  it('leaves what people wrote alone', () => {
    document.body.innerHTML = `
      <div class="ai-chat-msg"><p>Great job 🎉</p></div>
      <span class="fm-name">🎉 party.jpg</span>
      <pre>⚡ log line</pre><textarea>💾</textarea><div contenteditable="true">✨</div>`;
    iconizeTree(document.body);
    expect(document.querySelectorAll('svg.zi').length).toBe(0);
  });

  it('removes emoji from tooltips and placeholders', () => {
    document.body.innerHTML = '<input id="i" placeholder="🔍 Filter folders..."><a id="a" title="⚡ Wake">x</a>';
    iconizeTree(document.body);
    expect(document.getElementById('i').placeholder).toBe('Filter folders...');
    expect(document.getElementById('a').title).toBe('Wake');
  });

  it('gives icon-only buttons a name', () => {
    document.body.innerHTML = '<button id="t" title="Remove share">🗑️</button><button id="c">✕</button><button id="n" aria-label="Mine">🔄</button>';
    iconizeTree(document.body);
    expect(document.getElementById('t').getAttribute('aria-label')).toBe('Remove share');
    expect(document.getElementById('c').getAttribute('aria-label')).toBe('Close');
    expect(document.getElementById('n').getAttribute('aria-label')).toBe('Mine');
  });

  it('converts what is added or changed later', async () => {
    startIconizer();
    const el = document.createElement('div');
    el.innerHTML = '<span>📁 Shares</span>';
    document.body.appendChild(el);
    await Promise.resolve();
    expect(icons(el)).toEqual(['folder']);
    el.firstChild.textContent = '✅ Done';
    await Promise.resolve();
    expect(icons(el)).toEqual(['circle-check']);
  });

  it('helpers', () => {
    expect(stripEmoji('🚀 Setup completed!')).toBe('Setup completed!');
    expect(iconFor('⚠️')).toBe('triangle-alert');
    expect(iconHtml('zap')).toContain('#zi-zap');
    expect(iconHtml('@dot-red')).toContain('zi-dot-red');
  });

  it('has a sprite symbol for every mapped icon', () => {
    const sprite = readFileSync(join(__dirname, '..', '..', 'public', 'zi-sprite.svg'), 'utf8');
    for (const name of new Set(Object.values(EMOJI_ICONS))) {
      if (name.startsWith('@dot-')) continue;
      if (name.startsWith('@')) continue; // the page's own sprite (i-yak)
      expect(sprite, name).toContain(`id="zi-${name}"`);
    }
  });

  it('maps every emoji the translations use', () => {
    const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}]/gu;
    const dir = join(__dirname, '..', 'locales');
    const missing = new Set();
    for (const f of readdirSync(dir)) {
      for (const m of readFileSync(join(dir, f), 'utf8').matchAll(EMOJI)) if (!EMOJI_ICONS[m[0]]) missing.add(m[0]);
    }
    expect([...missing]).toEqual([]);
  });
});
