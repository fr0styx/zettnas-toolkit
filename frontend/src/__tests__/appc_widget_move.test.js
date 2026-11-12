/** APP-C: the widget list can be reordered with up and down buttons, not only by dragging. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('offline'))));
const { setLanguage } = await import('../i18n.js');
const W = await import('../components/widgets.js');

function list() {
  document.body.innerHTML = `<div id="l">${['clock', 'system', 'weather']
    .map((id) => `<div class="widget-sortable-item" data-widget-id="${id}"><div class="widget-sortable-left"><div class="wdg-xs-bold-strong">${id} widget</div></div><input type="checkbox"></div>`)
    .join('')}</div>`;
  return document.getElementById('l');
}
const btn = (l, id, dir) => l.querySelector(`[data-widget-id="${id}"] .widget-move-btn[data-move="${dir}"]`);

describe('widget move buttons', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('adds a named pair to each row, once, before the switch', () => {
    const l = list();
    W.addWidgetMoveButtons(l, () => {});
    W.addWidgetMoveButtons(l, () => {});
    expect(l.querySelectorAll('.widget-move-btn').length).toBe(6);
    expect(btn(l, 'system', 'up').getAttribute('aria-label')).toBe('Move system widget up');
    expect(btn(l, 'system', 'up').nextElementSibling.dataset.move).toBe('down');
    expect(l.querySelector('[data-widget-id="clock"] .widget-move').nextElementSibling.tagName).toBe('INPUT');
  });

  it('switches off up on the first row and down on the last', () => {
    const l = list();
    W.addWidgetMoveButtons(l, () => {});
    expect(btn(l, 'clock', 'up').disabled).toBe(true);
    expect(btn(l, 'clock', 'down').disabled).toBe(false);
    expect(btn(l, 'weather', 'down').disabled).toBe(true);
  });

  it('moves, saves the new order and keeps the focus', () => {
    const l = list();
    const save = vi.fn();
    W.addWidgetMoveButtons(l, save);
    btn(l, 'clock', 'down').click();
    expect(W.widgetOrder(l)).toEqual(['system', 'clock', 'weather']);
    expect(save).toHaveBeenLastCalledWith(['system', 'clock', 'weather']);
    expect(document.activeElement).toBe(btn(l, 'clock', 'down'));
    btn(l, 'clock', 'down').click();
    expect(W.widgetOrder(l)).toEqual(['system', 'weather', 'clock']);
    // at the end, the focus moves to the button that still works
    expect(document.activeElement).toBe(btn(l, 'clock', 'up'));
    btn(l, 'system', 'up').click();
    expect(save).toHaveBeenCalledTimes(2);
  });

  it('a move off either end does nothing', () => {
    const l = list();
    const save = vi.fn();
    W.addWidgetMoveButtons(l, save);
    W.moveWidgetRow(l, l.querySelector('[data-widget-id="clock"]'), 'up', save);
    W.moveWidgetRow(l, l.querySelector('[data-widget-id="weather"]'), 'down', save);
    expect(save).not.toHaveBeenCalled();
  });

  it('renames the buttons in the language chosen', async () => {
    const l = list();
    W.addWidgetMoveButtons(l, () => {});
    await setLanguage('de');
    W.refreshWidgetMoveButtons(l);
    expect(btn(l, 'system', 'down').getAttribute('aria-label')).toBe('system widget nach unten');
  });
});
