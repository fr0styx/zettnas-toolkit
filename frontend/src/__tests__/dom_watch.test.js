// PERF-8: one MutationObserver for the page, observing only what its subscribers ask for.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { _test, addedNodes, watchDom } from '../dom-watch.js';

const flush = () => Promise.resolve();

describe('the shared page watcher', () => {
  const stops = [];
  afterEach(() => {
    stops.splice(0).forEach((stop) => stop());
    document.body.innerHTML = '';
  });

  it('observes once, for the union of what subscribers need, and stops when nobody listens', () => {
    stops.push(watchDom({ onRecords: () => {} }));
    expect(_test.options()).toEqual({ childList: true, subtree: true });
    const stopAttrs = watchDom({ attributes: ['class'], characterData: true, onRecords: () => {} });
    expect(_test.options()).toEqual({ childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['class'] });
    stopAttrs();
    expect(_test.options()).toEqual({ childList: true, subtree: true });
    stops.pop()();
    expect(_test.options()).toBe(null);
    expect(_test.count()).toBe(0);
  });

  it('gives each subscriber added nodes, and only the text and attribute changes it asked for', async () => {
    const plain = vi.fn();
    const classes = vi.fn();
    stops.push(watchDom({ onRecords: plain }), watchDom({ attributes: ['class'], onRecords: classes }));
    const el = document.createElement('div');
    document.body.appendChild(el);
    await flush();
    expect(addedNodes(plain.mock.calls[0][0])).toEqual([el]);
    el.className = 'x';
    el.title = 'not watched';
    await flush();
    expect(plain).toHaveBeenCalledTimes(1);
    expect(classes).toHaveBeenCalledTimes(2);
    expect(classes.mock.calls[1][0].map((r) => r.attributeName)).toEqual(['class']);
  });

  it('a failing subscriber does not stop the others', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const ok = vi.fn();
    stops.push(watchDom({ onRecords: () => { throw new Error('boom'); } }), watchDom({ onRecords: ok }));
    document.body.appendChild(document.createElement('p'));
    await flush();
    expect(ok).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
