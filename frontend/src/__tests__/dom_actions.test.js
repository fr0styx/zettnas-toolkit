import { describe, it, expect, vi } from 'vitest';
import { installDomActions } from '../dom-actions.js';

describe('delegated DOM actions replace inline handlers (FE-06)', () => {
  installDomActions();

  it('clicks and hides targets and opens previews', () => {
    document.body.innerHTML = `<input id="up" type="file"><div id="m">x</div>
      <button id="b1" data-action="click-target" data-target="up"></button>
      <button id="b2" data-action="hide-target" data-target="m"></button>
      <button id="b3" data-action="open-file-preview" data-path="/a&#39;b.jpg" data-name="a&#39;b"></button>`;
    const clicked = vi.fn();
    document.getElementById('up').addEventListener('click', clicked);
    document.getElementById('b1').click();
    expect(clicked).toHaveBeenCalled();
    document.getElementById('b2').click();
    expect(document.getElementById('m').style.display).toBe('none');
    window.openFilePreviewModal = vi.fn();
    document.getElementById('b3').click();
    expect(window.openFilePreviewModal).toHaveBeenCalledWith("/a'b.jpg", "a'b"); // quotes stay data, never code
  });

  it('handles image fallbacks', () => {
    document.body.innerHTML = '<img id="i" data-img-fallback="hide-show-next:flex"><span id="n" style="display:none"></span>';
    document.getElementById('i').dispatchEvent(new Event('error'));
    expect(document.getElementById('i').style.display).toBe('none');
    expect(document.getElementById('n').style.display).toBe('flex');
  });
});
