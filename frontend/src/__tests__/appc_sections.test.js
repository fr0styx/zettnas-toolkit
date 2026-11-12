/** Mission Control opens tabs that hold several panes, by link, by default and by click (APP-C). */
import { describe, it, expect, vi, beforeAll } from 'vitest';
import { initManagement } from '../components/management.js';
import { api } from '../api.js';

const shown = (id) => document.getElementById(id).style.display;
const active = (sel) => document.querySelector(sel).classList.contains('active');

describe('Mission Control tab groups (APP-C)', () => {
  beforeAll(() => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    vi.spyOn(api, 'post').mockResolvedValue({});
    Element.prototype.scrollIntoView = vi.fn();
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"></div>
        <div class="mgmt-content-pane">
          <div id="mgmt-sec-wallpaper" class="mgmt-detail-card">
            <div class="mgmt-inner-tabs" role="tablist">
              <button class="mgmt-inner-tab active" data-tab-target="mgmt-pane-theme" data-tab-panes="mgmt-pane-theme mgmt-pane-wallpaper mgmt-pane-glass" id="look"></button>
              <button class="mgmt-inner-tab" data-tab-target="mgmt-pane-dock" data-tab-panes="mgmt-pane-dock mgmt-pane-widgets mgmt-pane-screensaver" id="desk"></button>
            </div>
            <div class="mgmt-tab-pane" id="mgmt-pane-theme"></div><div class="mgmt-tab-pane" id="mgmt-pane-wallpaper"></div>
            <div class="mgmt-tab-pane" id="mgmt-pane-glass"></div><div class="mgmt-tab-pane" id="mgmt-pane-dock"></div>
            <div class="mgmt-tab-pane" id="mgmt-pane-widgets"></div><div class="mgmt-tab-pane" id="mgmt-pane-screensaver"></div>
            <div class="mgmt-tab-pane" id="mgmt-pane-loose"></div>
          </div>
          <div id="mgmt-sec-docker" class="mgmt-detail-card">
            <div class="mgmt-inner-tabs" role="tablist">
              <button class="mgmt-inner-tab active" data-tab-target="mgmt-pane-docker" id="apps"></button>
              <button class="mgmt-inner-tab" data-tab-target="mgmt-pane-docker-catalog" id="cat"></button>
            </div>
            <div class="mgmt-tab-pane" id="mgmt-pane-docker"></div>
          </div>
          <div id="mgmt-sec-zz" class="mgmt-detail-card">
            <div class="mgmt-inner-tabs" role="tablist">
              <button class="mgmt-inner-tab" data-tab-target="zz-a" id="zz-first"></button>
              <button class="mgmt-inner-tab active" data-tab-target="zz-b" data-tab-panes="zz-b zz-c" id="zz-group"></button>
            </div>
            <div class="mgmt-tab-pane" id="zz-a"></div><div class="mgmt-tab-pane" id="zz-b"></div><div class="mgmt-tab-pane" id="zz-c"></div>
          </div>
          <div id="mgmt-sec-ai" class="mgmt-detail-card">
            <div class="mgmt-inner-tabs" role="tablist"><button class="mgmt-inner-tab active" data-tab-target="mgmt-pane-ai-chat" id="chat"></button></div>
            <div class="mgmt-tab-pane" id="mgmt-pane-ai-chat"></div>
          </div>
        </div></div></div>`;
    try { initManagement(); } catch (_) { /* parts of the window this test doesn't build */ }
  });

  it('a link to a pane of a group opens its tab, shows the group and scrolls to the pane', () => {
    window.openManagementWindow('mgmt-sec-wallpaper', 'mgmt-pane-glass');
    expect(active('#look')).toBe(true);
    expect(['mgmt-pane-theme', 'mgmt-pane-wallpaper', 'mgmt-pane-glass', 'mgmt-pane-dock'].map(shown)).toEqual(['block', 'block', 'block', 'none']);
    expect(document.getElementById('mgmt-pane-glass').scrollIntoView).toHaveBeenCalled();
  });

  it('a click shows the other group', () => {
    document.getElementById('desk').click();
    expect(active('#desk')).toBe(true);
    expect(['mgmt-pane-dock', 'mgmt-pane-widgets', 'mgmt-pane-screensaver', 'mgmt-pane-theme'].map(shown)).toEqual(['block', 'block', 'block', 'none']);
  });

  it('opening Appearance by name shows Look (the link names the wallpaper pane)', () => {
    window.openManagementWindow('mgmt-sec-wallpaper');
    expect(active('#look')).toBe(true);
    expect(shown('mgmt-pane-glass')).toBe('block');
    expect(shown('mgmt-pane-dock')).toBe('none');
  });

  it('a section opened without a pane shows its active tab\'s whole group', () => {
    window.openManagementWindow('mgmt-sec-zz');
    expect(['zz-a', 'zz-b', 'zz-c'].map(shown)).toEqual(['none', 'block', 'block']);
  });

  it('a pane outside every tab still opens on its own', () => {
    window.openManagementWindow('mgmt-sec-wallpaper', 'mgmt-pane-loose');
    expect(shown('mgmt-pane-loose')).toBe('block');
    expect(active('#look') || active('#desk')).toBe(false);
  });

  it('the catalog shows the apps pane, and the chat pane is a column', () => {
    window.openManagementWindow('mgmt-sec-docker', 'mgmt-pane-docker-catalog');
    expect(active('#cat')).toBe(true);
    expect(shown('mgmt-pane-docker')).toBe('block');
    window.openManagementWindow('mgmt-sec-ai', 'mgmt-pane-ai-chat');
    expect(shown('mgmt-pane-ai-chat')).toBe('flex');
    window.openManagementWindow('mgmt-sec-ai');
    expect(shown('mgmt-pane-ai-chat')).toBe('flex');
  });
});
