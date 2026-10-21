import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { initSynchronizedTableScrollbars } from '../components/docker-table.js';

describe('Docker Container Table: Synchronized Top and Sticky Horizontal Scrollbars', () => {
  let tableWrapEl;
  let topScrollEl;
  let stickyScrollEl;
  let table;
  let topInner;
  let stickyInner;

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="test-container" style="width: 500px;">
        <div class="docker-table-top-scroll" id="docker-table-top-scroll" style="display: none;">
          <div class="docker-table-top-scroll-inner"></div>
        </div>
        <div class="docker-table-container" style="overflow-x: auto; width: 500px;">
          <table style="width: 1200px;">
            <thead>
              <tr>
                <th>Name</th><th>Stack</th><th>Hardware</th><th>CPU</th><th>Ports</th><th>Status</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr><td>container-1</td><td>arr</td><td>NVIDIA</td><td>1.2%</td><td>:8080</td><td>running</td><td>acts</td></tr>
            </tbody>
          </table>
        </div>
        <div class="docker-table-sticky-scroll" id="docker-table-sticky-scroll" style="display: none;">
          <div class="docker-table-sticky-scroll-inner"></div>
        </div>
      </div>
    `;

    tableWrapEl = document.querySelector('.docker-table-container');
    topScrollEl = document.getElementById('docker-table-top-scroll');
    stickyScrollEl = document.getElementById('docker-table-sticky-scroll');
    table = tableWrapEl.querySelector('table');
    topInner = topScrollEl.querySelector('.docker-table-top-scroll-inner');
    stickyInner = stickyScrollEl.querySelector('.docker-table-sticky-scroll-inner');

    // Mock clientWidth and scrollWidth for jsdom
    Object.defineProperty(tableWrapEl, 'clientWidth', { configurable: true, value: 500 });
    Object.defineProperty(tableWrapEl, 'scrollWidth', { configurable: true, value: 1200 });
    Object.defineProperty(table, 'scrollWidth', { configurable: true, value: 1200 });
    Object.defineProperty(table, 'offsetWidth', { configurable: true, value: 1200 });
  });

  afterEach(() => {
    if (tableWrapEl && tableWrapEl._syncScrollbarsController) {
      tableWrapEl._syncScrollbarsController.destroy();
    }
  });

  it('detects horizontal overflow and displays top and sticky bottom scrollbars', () => {
    const controller = initSynchronizedTableScrollbars(tableWrapEl, topScrollEl, stickyScrollEl);

    expect(topScrollEl.style.display).toBe('block');
    expect(stickyScrollEl.style.display).toBe('block');
    expect(topInner.style.width).toBe('1200px');
    expect(stickyInner.style.width).toBe('1200px');

    controller.destroy();
  });

  it('hides top and sticky scrollbars when table fits without overflow', () => {
    // Make table fit inside container
    Object.defineProperty(table, 'scrollWidth', { configurable: true, value: 450 });
    Object.defineProperty(table, 'offsetWidth', { configurable: true, value: 450 });
    Object.defineProperty(tableWrapEl, 'scrollWidth', { configurable: true, value: 500 });

    const controller = initSynchronizedTableScrollbars(tableWrapEl, topScrollEl, stickyScrollEl);

    expect(topScrollEl.style.display).toBe('none');
    expect(stickyScrollEl.style.display).toBe('none');

    controller.destroy();
  });

  it('synchronizes table container and sticky scrollbar when top scrollbar is scrolled', () => {
    const controller = initSynchronizedTableScrollbars(tableWrapEl, topScrollEl, stickyScrollEl);

    topScrollEl.scrollLeft = 280;
    topScrollEl.dispatchEvent(new Event('scroll'));

    expect(tableWrapEl.scrollLeft).toBe(280);
    expect(stickyScrollEl.scrollLeft).toBe(280);

    controller.destroy();
  });

  it('synchronizes table container and top scrollbar when sticky bottom scrollbar is scrolled', () => {
    const controller = initSynchronizedTableScrollbars(tableWrapEl, topScrollEl, stickyScrollEl);

    stickyScrollEl.scrollLeft = 340;
    stickyScrollEl.dispatchEvent(new Event('scroll'));

    expect(tableWrapEl.scrollLeft).toBe(340);
    expect(topScrollEl.scrollLeft).toBe(340);

    controller.destroy();
  });

  it('synchronizes top and sticky scrollbars when the table container itself is scrolled', () => {
    const controller = initSynchronizedTableScrollbars(tableWrapEl, topScrollEl, stickyScrollEl);

    tableWrapEl.scrollLeft = 450;
    tableWrapEl.dispatchEvent(new Event('scroll'));

    expect(topScrollEl.scrollLeft).toBe(450);
    expect(stickyScrollEl.scrollLeft).toBe(450);

    controller.destroy();
  });

  it('handles null or missing top/sticky elements gracefully without throwing', () => {
    expect(() => {
      const ctrl = initSynchronizedTableScrollbars(tableWrapEl, null, null);
      ctrl.update();
      ctrl.destroy();
    }).not.toThrow();

    expect(() => {
      const ctrl = initSynchronizedTableScrollbars(null, null, null);
      ctrl.update();
      ctrl.destroy();
    }).not.toThrow();
  });
});
