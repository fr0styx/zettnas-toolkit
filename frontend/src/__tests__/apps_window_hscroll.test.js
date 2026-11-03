// The Apps window's horizontal scrollbar is on the window's bottom edge (outside the scrolling area)
import { describe, it, expect, afterEach } from 'vitest';
import { initSynchronizedTableScrollbars } from '../components/docker-table.js';

describe('a bottom scrollbar wider than the table', () => {
  let wrap;
  afterEach(() => wrap?._syncScrollbarsController?.destroy());

  it('gets the same scroll range as the table', () => {
    document.body.innerHTML = `
      <div class="wrap" style="overflow-x:auto"><table></table></div>
      <div class="docker-table-sticky-scroll" style="display:none"><div class="docker-table-sticky-scroll-inner"></div></div>`;
    wrap = document.querySelector('.wrap');
    const table = wrap.querySelector('table');
    const bar = document.querySelector('.docker-table-sticky-scroll');
    Object.defineProperty(wrap, 'clientWidth', { configurable: true, value: 500 });
    Object.defineProperty(wrap, 'scrollWidth', { configurable: true, value: 1200 });
    Object.defineProperty(table, 'scrollWidth', { configurable: true, value: 1200 });
    Object.defineProperty(bar, 'clientWidth', { configurable: true, value: 540 });
    initSynchronizedTableScrollbars(wrap, null, bar);
    expect(bar.style.display).toBe('block');
    // 1200 - 500 = 700 px to scroll in the table; 1240 - 540 = 700 px in the bar
    expect(bar.firstElementChild.style.width).toBe('1240px');
  });
});
