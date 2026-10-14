import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'fs';
import path from 'path';
import { initContainersManager, openContainersManager } from '../components/containers-manager.js';

describe('Containers Manager Mobile Touch Scrolling & Ergonomics', () => {
  const cssPath = path.resolve(__dirname, '../style.css');
  const cssContent = fs.readFileSync(cssPath, 'utf8');

  beforeEach(() => {
    document.body.innerHTML = '';
    window._containersManagerInitialized = false;
  });

  it('enforces min-height: 0 and touch-action: pan-y on .containers-content-body in CSS', () => {
    expect(cssContent).toMatch(/\.containers-content-body[\s\S]*?min-height:\s*0\s*!important/);
    expect(cssContent).toMatch(/\.containers-content-body[\s\S]*?overflow-y:\s*auto\s*!important/);
    expect(cssContent).toMatch(/\.containers-content-body[\s\S]*?touch-action:\s*pan-y\s*!important/);
  });

  it('enforces horizontal swipe and nowrap on mobile telemetry action buttons and filter pills', () => {
    expect(cssContent).toMatch(/\.cw-action-btns-wrap[\s\S]*?overflow-x:\s*auto\s*!important/);
    expect(cssContent).toMatch(/\.cw-action-btns-wrap[\s\S]*?flex-wrap:\s*nowrap\s*!important/);
    expect(cssContent).toMatch(/\.cw-docker-filter-pills[\s\S]*?overflow-x:\s*auto\s*!important/);
    expect(cssContent).toMatch(/\.cw-docker-filter-pills[\s\S]*?flex-wrap:\s*nowrap\s*!important/);
  });

  it('enforces flex-shrink: 0 on .containers-telemetry-header on mobile', () => {
    expect(cssContent).toMatch(/\.containers-telemetry-header[\s\S]*?flex-shrink:\s*0\s*!important/);
  });

  it('renders containers manager window with touch-action and min-height on content body', () => {
    initContainersManager();
    const win = document.getElementById('containers-manager-window');
    expect(win).not.toBeNull();

    const contentBody = win.querySelector('.containers-content-body');
    expect(contentBody).not.toBeNull();
    expect(contentBody.style.minHeight).toBe('0px');
    expect(contentBody.style.overflowY).toBe('auto');

    const tableWrap = win.querySelector('.cw-docker-table-wrap');
    expect(tableWrap).not.toBeNull();

    const actionWrap = win.querySelector('.cw-action-btns-wrap');
    expect(actionWrap).not.toBeNull();

    const searchWrap = win.querySelector('.cw-docker-search-wrap');
    expect(searchWrap).not.toBeNull();
  });
});
