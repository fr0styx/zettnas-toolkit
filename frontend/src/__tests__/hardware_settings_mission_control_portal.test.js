import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  initSettings,
  openDrawer,
  closeDrawer,
  mountTabsInDrawer,
  restoreHardwareTabsToManagement
} from '../components/settings.js';
import {
  SUBPANE_MAP
} from '../components/management.js';
import { api } from '../api.js';

describe('Hardware Settings Mission Control Portal & Bi-Directional Reparenting', () => {
  beforeEach(() => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    document.body.innerHTML = `
      <div id="management-modal-overlay" class="open" style="display: flex;">
        <div id="management-modal-window">
          <div id="mgmt-sec-hardware" class="mgmt-detail-card">
            <div class="mgmt-inner-tabs" role="tablist">
              <button class="mgmt-inner-tab active" data-tab-target="mgmt-pane-unraid">Host & Profiles</button>
              <button class="mgmt-inner-tab" data-tab-target="mgmt-pane-hardware-lcd">Dashboard Layout</button>
              <button class="mgmt-inner-tab" data-tab-target="mgmt-pane-hardware-led">LED Strip bar</button>
              <button class="mgmt-inner-tab" data-tab-target="mgmt-pane-hardware-fans">Fans</button>
              <button class="mgmt-inner-tab" data-tab-target="mgmt-pane-hardware-copy">Copy Button</button>
            </div>

            <div id="mgmt-pane-unraid" class="mgmt-tab-pane" style="display: block;">
            </div>

            <div id="mgmt-pane-hardware-lcd" class="mgmt-tab-pane" style="display: none;">
              <button id="btn-open-lcd-drawer">Open Drawer</button>
              <div id="mgmt-pane-hardware-lcd-slot" class="mgmt-hardware-tab-slot"></div>
            </div>

            <div id="mgmt-pane-hardware-led" class="mgmt-tab-pane" style="display: none;">
              <button id="btn-open-led-drawer">Open Drawer</button>
              <div id="mgmt-pane-hardware-led-slot" class="mgmt-hardware-tab-slot"></div>
            </div>

            <div id="mgmt-pane-hardware-fans" class="mgmt-tab-pane" style="display: none;">
              <button id="btn-open-fans-drawer">Open Drawer</button>
              <div id="mgmt-pane-hardware-fans-slot" class="mgmt-hardware-tab-slot"></div>
            </div>

            <div id="mgmt-pane-hardware-copy" class="mgmt-tab-pane" style="display: none;">
              <button id="btn-open-copy-drawer">Open Drawer</button>
              <div id="mgmt-pane-hardware-copy-slot" class="mgmt-hardware-tab-slot"></div>
            </div>
          </div>
        </div>
      </div>

      <div id="drawer-overlay" class="drawer-backdrop"></div>
      <aside id="led-drawer" class="slide-drawer">
        <div class="drawer-tabs-nav">
          <button class="drawer-tab-btn active" data-tab="tab-layout">Dashboard Layout</button>
          <button class="drawer-tab-btn" data-tab="tab-led">LED Strip bar</button>
          <button class="drawer-tab-btn" data-tab="tab-fans">Fans</button>
          <button class="drawer-tab-btn" data-tab="tab-buttons">Copy Button</button>
        </div>
        <div id="drawer-tabs-container">
          <div id="tab-layout" class="drawer-tab-content active">Layout Content</div>
          <div id="tab-led" class="drawer-tab-content">LED Content</div>
          <div id="tab-fans" class="drawer-tab-content">Fans Content</div>
          <div id="tab-buttons" class="drawer-tab-content">Copy Content</div>
        </div>
      </aside>
    `;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('SUBPANE_MAP correctly routes mgmt-pane-hardware-copy to mgmt-sec-hardware', () => {
    expect(SUBPANE_MAP['mgmt-pane-hardware-copy']).toEqual({
      section: 'mgmt-sec-hardware',
      pane: 'mgmt-pane-hardware-copy'
    });
    expect(SUBPANE_MAP['mgmt-pane-hardware-fans']).toEqual({
      section: 'mgmt-sec-hardware',
      pane: 'mgmt-pane-hardware-fans'
    });
    expect(SUBPANE_MAP['mgmt-pane-hardware-led']).toEqual({
      section: 'mgmt-sec-hardware',
      pane: 'mgmt-pane-hardware-led'
    });
    expect(SUBPANE_MAP['mgmt-pane-hardware-lcd']).toEqual({
      section: 'mgmt-sec-hardware',
      pane: 'mgmt-pane-hardware-lcd'
    });
  });

  it('restoreHardwareTabsToManagement reparents all 4 hardware tabs into Mission Control slots', () => {
    const lcdSlot = document.getElementById('mgmt-pane-hardware-lcd-slot');
    const ledSlot = document.getElementById('mgmt-pane-hardware-led-slot');
    const fansSlot = document.getElementById('mgmt-pane-hardware-fans-slot');
    const copySlot = document.getElementById('mgmt-pane-hardware-copy-slot');

    const tabLayout = document.getElementById('tab-layout');
    const tabLed = document.getElementById('tab-led');
    const tabFans = document.getElementById('tab-fans');
    const tabButtons = document.getElementById('tab-buttons');

    // Initially in drawer
    expect(tabLayout.parentElement.id).toBe('drawer-tabs-container');

    restoreHardwareTabsToManagement();

    expect(tabLayout.parentElement).toBe(lcdSlot);
    expect(tabLed.parentElement).toBe(ledSlot);
    expect(tabFans.parentElement).toBe(fansSlot);
    expect(tabButtons.parentElement).toBe(copySlot);
  });

  it('openDrawer reparents tabs back into drawer and closeDrawer restores them to Mission Control', () => {
    const drawer = document.getElementById('led-drawer');
    const overlay = document.getElementById('drawer-overlay');
    const fansSlot = document.getElementById('mgmt-pane-hardware-fans-slot');
    const tabFans = document.getElementById('tab-fans');

    // Move to Mission Control
    restoreHardwareTabsToManagement();
    expect(tabFans.parentElement).toBe(fansSlot);

    // Open drawer to Fans tab
    openDrawer('tab-fans');
    expect(drawer.classList.contains('open')).toBe(true);
    expect(overlay.classList.contains('open')).toBe(true);
    expect(tabFans.parentElement.id).toBe('drawer-tabs-container');
    expect(tabFans.classList.contains('active')).toBe(true);

    // While drawer is open, calling restoreHardwareTabsToManagement does not prematurely steal tabs
    restoreHardwareTabsToManagement();
    expect(tabFans.parentElement.id).toBe('drawer-tabs-container');

    // Close drawer
    closeDrawer();
    expect(drawer.classList.contains('open')).toBe(false);
    expect(overlay.classList.contains('open')).toBe(false);
    expect(tabFans.parentElement).toBe(fansSlot);
  });

  it('mountTabsInDrawer sets active class on the currently selected drawer tab', () => {
    const tabLayout = document.getElementById('tab-layout');
    const tabLed = document.getElementById('tab-led');
    const tabFans = document.getElementById('tab-fans');
    const tabButtons = document.getElementById('tab-buttons');

    restoreHardwareTabsToManagement();

    // Select Fans in drawer nav
    document.querySelectorAll('.drawer-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.drawer-tab-btn[data-tab="tab-fans"]').classList.add('active');

    mountTabsInDrawer();

    expect(tabFans.classList.contains('active')).toBe(true);
    expect(tabLayout.classList.contains('active')).toBe(false);
    expect(tabLed.classList.contains('active')).toBe(false);
    expect(tabButtons.classList.contains('active')).toBe(false);
  });

  it('openDrawer opens to Dashboard Layout tab by default and marks #tab-layout as active even when invoked by MouseEvent', () => {
    const tabLayout = document.getElementById('tab-layout');
    const layoutTabBtn = document.querySelector('.drawer-tab-btn[data-tab="tab-layout"]');

    restoreHardwareTabsToManagement();
    expect(tabLayout.parentElement.id).not.toBe('drawer-tabs-container');

    // Simulate clicking toggleBtn which passes a MouseEvent to openDrawer
    const fakeMouseEvent = new MouseEvent('click');
    openDrawer(fakeMouseEvent);

    expect(tabLayout.parentElement.id).toBe('drawer-tabs-container');
    expect(tabLayout.classList.contains('active')).toBe(true);
    expect(layoutTabBtn.classList.contains('active')).toBe(true);

    closeDrawer();
  });

  it('preserves tab activation when switching to another tab and back to Dashboard Layout', () => {
    initSettings();
    const tabLayout = document.getElementById('tab-layout');
    const tabFans = document.getElementById('tab-fans');
    const layoutTabBtn = document.querySelector('.drawer-tab-btn[data-tab="tab-layout"]');
    const fansTabBtn = document.querySelector('.drawer-tab-btn[data-tab="tab-fans"]');

    restoreHardwareTabsToManagement();
    openDrawer();

    expect(tabLayout.classList.contains('active')).toBe(true);

    // Switch to Fans tab
    fansTabBtn.click();
    expect(tabFans.classList.contains('active')).toBe(true);
    expect(tabLayout.classList.contains('active')).toBe(false);

    // Switch back to Dashboard Layout
    layoutTabBtn.click();
    expect(tabLayout.classList.contains('active')).toBe(true);
    expect(tabFans.classList.contains('active')).toBe(false);

    closeDrawer();
  });
});

