import { describe, it, expect, vi } from 'vitest';
import { FileManagerWindow } from '../components/file-manager.js';

// jsdom has no layout: give the path bar a width and make each piece take 60px
function fakeExplorer(path, width) {
  const box = document.createElement('div');
  Object.defineProperty(box, 'clientWidth', { get: () => width });
  Object.defineProperty(box, 'scrollWidth', { get: () => box.children.length * 60 });
  document.body.appendChild(box);
  return { breadcrumbs: box, currentPath: path, loadPath: vi.fn(), showBreadcrumbsDropdown: vi.fn() };
}
const render = (fm) => FileManagerWindow.prototype.renderBreadcrumbs.call(fm);
const texts = (fm) => Array.from(fm.breadcrumbs.children).map((c) => c.textContent);

describe('File Explorer path bar', () => {
  const deep = '/mnt/user/vault/Movies/(500) Days of Summer (2009)';

  it('shows every folder when there is room', () => {
    const fm = fakeExplorer(deep, 2000);
    render(fm);
    expect(texts(fm)).toEqual(['/', 'mnt', '/', 'user', '/', 'vault', '/', 'Movies', '/', '(500) Days of Summer (2009)']);
    expect(fm.breadcrumbs.querySelector('.fm-breadcrumb-ellipsis')).toBeNull();
  });

  it('folds only as many middle folders as needed, keeping the first and the last', () => {
    const fm = fakeExplorer(deep, 8 * 60);
    render(fm);
    expect(texts(fm)).toEqual(['/', 'mnt', '/', '...', '/', 'Movies', '/', '(500) Days of Summer (2009)']);
    fm.breadcrumbs.querySelector('.fm-breadcrumb-ellipsis').click();
    expect(fm.showBreadcrumbsDropdown).toHaveBeenCalledWith(expect.anything(), ['mnt', 'user', 'vault', 'Movies', '(500) Days of Summer (2009)'], 1, 3);
  });

  it('does not fold before the bar has a size, and has no stray separator after the root', () => {
    const fm = fakeExplorer(deep, 0);
    render(fm);
    expect(texts(fm).slice(0, 3)).toEqual(['/', 'mnt', '/']);
    expect(fm.breadcrumbs.querySelector('.fm-breadcrumb-ellipsis')).toBeNull();
  });
});
