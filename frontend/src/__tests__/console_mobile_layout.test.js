import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'fs';
import path from 'path';
import { openConsoleWindow } from '../components/dock.js';

describe('ZettNAS System Console Mobile Layout & Screen Adaptation Suite', () => {
  const cssPath = path.resolve(__dirname, '../style.css');
  const cssContent = fs.readFileSync(cssPath, 'utf8');

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="console-modal-overlay" class="smart-modal-backdrop window-minimized" style="display: none;">
        <div class="chassis-front-panel" id="console-window" style="position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);">
          <div class="chassis-panel-header">
            <span class="chassis-engraved-text" id="chassis-panel-engraved">ZETTNAS • SYSTEM CONSOLE</span>
            <div style="display:flex; gap:12px; align-items:center;">
              <span class="chassis-screen-spec">640 × 172 IPS</span>
              <div class="os-window-controls">
                <button class="win-btn min-btn" id="console-min" title="Minimize to dock" aria-label="Minimize"></button>
                <button class="win-btn max-btn" id="console-max" title="Maximize" aria-label="Maximize"></button>
                <button class="win-btn close-btn" id="console-close" title="Close console window" aria-label="Close"></button>
              </div>
            </div>
          </div>
          <div id="screen" class="hardware-screen-canvas">
            <header>
              <div class="h-left">
                <span class="nas-name" id="nasName">NAS</span>
                <span class="pill" id="statusPill"><span class="pill-dot"></span><span id="statusText">– OK</span></span>
              </div>
              <div class="clock" id="clock">--:--</div>
              <div class="h-right">
                <div class="lcd-page-dots" id="lcd-page-dots">
                  <span class="lcd-dot active" data-page="0">1</span>
                  <span class="lcd-dot" data-page="1">2</span>
                  <span class="lcd-dot" data-page="2">3</span>
                  <span class="lcd-dot" data-page="3">4</span>
                </div>
                <span id="ip">10.40.30.249</span>
              </div>
            </header>
            <div id="lcd-viewport" class="lcd-viewport">
              <div class="lcd-page active" id="lcd-page-0" data-page-index="0">
                <section class="cards" id="dashboard-cards-container">
                  <div class="card card-storage" data-metric-id="metric-storage"></div>
                  <div class="card card-cpu" data-metric-id="metric-cpu"></div>
                  <div class="card card-mem" data-metric-id="metric-mem"></div>
                  <div class="card fans card-fans" data-metric-id="metric-fans"></div>
                  <div class="card card-net" data-metric-id="metric-net"></div>
                </section>
                <section class="disks card-disks" id="diskRow" data-metric-id="metric-disks"></section>
              </div>
            </div>
          </div>
          <div class="chassis-led-fixture">
            <div class="chassis-led-channel">
              <div id="virtual-chassis-lightbar" class="chassis-lightbar-glow"></div>
            </div>
          </div>
        </div>
      </div>
    `;
    window.DockManager = {
      windows: {},
      register: (id, el, icon, title, pinned) => {
        window.DockManager.windows[id] = { id, el, icon, title, pinned };
      },
      restore: () => {},
      isPinned: () => false,
      render: () => {},
    };
  });

  it('enforces width 100vw, min-width 0, and touch scrolling on #console-window in mobile CSS', () => {
    // Check both @media (max-width: 768px) and body.mobile-mode
    expect(cssContent).toMatch(/#console-window\.chassis-front-panel[\s\S]*?width:\s*100vw\s*!important/);
    expect(cssContent).toMatch(/#console-window\.chassis-front-panel[\s\S]*?min-width:\s*0\s*!important/);
    expect(cssContent).toMatch(/#console-window\.chassis-front-panel[\s\S]*?overflow-y:\s*auto\s*!important/);
    expect(cssContent).toMatch(/#console-window\.chassis-front-panel[\s\S]*?touch-action:\s*pan-y\s*!important/);
    expect(cssContent).toMatch(/#console-window\.chassis-front-panel[\s\S]*?transform:\s*none\s*!important/);

    expect(cssContent).toMatch(/body\.mobile-mode #console-window\.chassis-front-panel[\s\S]*?width:\s*100vw\s*!important/);
    expect(cssContent).toMatch(/body\.mobile-mode #console-window\.chassis-front-panel[\s\S]*?min-width:\s*0\s*!important/);
    expect(cssContent).toMatch(/body\.mobile-mode #console-window\.chassis-front-panel[\s\S]*?overflow-y:\s*auto\s*!important/);
    expect(cssContent).toMatch(/body\.mobile-mode #console-window\.chassis-front-panel[\s\S]*?touch-action:\s*pan-y\s*!important/);
  });

  it('enforces height: auto, width: 100%, and visible overflow on #console-window #screen', () => {
    expect(cssContent).toMatch(/#console-window #screen[\s\S]*?width:\s*100%\s*!important/);
    expect(cssContent).toMatch(/#console-window #screen[\s\S]*?height:\s*auto\s*!important/);
    expect(cssContent).toMatch(/#console-window #screen[\s\S]*?overflow:\s*visible\s*!important/);

    expect(cssContent).toMatch(/body\.mobile-mode #console-window #screen[\s\S]*?width:\s*100%\s*!important/);
    expect(cssContent).toMatch(/body\.mobile-mode #console-window #screen[\s\S]*?height:\s*auto\s*!important/);
    expect(cssContent).toMatch(/body\.mobile-mode #console-window #screen[\s\S]*?overflow:\s*visible\s*!important/);
  });

  it('enforces flex-wrap: wrap on #screen header and 100% width on .h-right for phone readability', () => {
    expect(cssContent).toMatch(/#console-window #screen header[\s\S]*?flex-wrap:\s*wrap\s*!important/);
    expect(cssContent).toMatch(/#console-window #screen \.h-right[\s\S]*?width:\s*100%\s*!important/);
    expect(cssContent).toMatch(/#console-window #screen \.h-right[\s\S]*?justify-content:\s*space-between\s*!important/);

    expect(cssContent).toMatch(/body\.mobile-mode #console-window #screen header[\s\S]*?flex-wrap:\s*wrap\s*!important/);
    expect(cssContent).toMatch(/body\.mobile-mode #console-window #screen \.h-right[\s\S]*?width:\s*100%\s*!important/);
  });

  it('enforces 2-column responsive grid on .cards and full-width span on .card-storage', () => {
    expect(cssContent).toMatch(/#console-window \.cards[\s\S]*?grid-template-columns:\s*repeat\(2,\s*1fr\)\s*!important/);
    expect(cssContent).toMatch(/#console-window \.card\.card-storage[\s\S]*?grid-column:\s*1\s*\/\s*-1\s*!important/);

    expect(cssContent).toMatch(/body\.mobile-mode #console-window \.cards[\s\S]*?grid-template-columns:\s*repeat\(2,\s*1fr\)\s*!important/);
    expect(cssContent).toMatch(/body\.mobile-mode #console-window \.card\.card-storage[\s\S]*?grid-column:\s*1\s*\/\s*-1\s*!important/);
  });

  it('enforces responsive wrapping on disk inventory, bay matrix, and telemetry panels', () => {
    expect(cssContent).toMatch(/#console-window \.disks[\s\S]*?flex-direction:\s*column\s*!important/);
    expect(cssContent).toMatch(/#console-window \.group-tiles[\s\S]*?grid-template-columns:\s*repeat\(auto-fill,\s*minmax\(130px,\s*1fr\)\)\s*!important/);
    expect(cssContent).toMatch(/#console-window \.bay-matrix-grid[\s\S]*?grid-template-columns:\s*repeat\(auto-fill,\s*minmax\(95px,\s*1fr\)\)\s*!important/);
    expect(cssContent).toMatch(/#console-window \.net-io-grid[\s\S]*?flex-direction:\s*column\s*!important/);
    expect(cssContent).toMatch(/#console-window \.unraid-copy-grid[\s\S]*?flex-direction:\s*column\s*!important/);
  });

  it('enforces width: 100% and overflow: hidden on the ARGB lightbar fixture', () => {
    expect(cssContent).toMatch(/#console-window \.chassis-led-fixture[\s\S]*?width:\s*100%\s*!important/);
    expect(cssContent).toMatch(/#console-window \.chassis-led-channel[\s\S]*?overflow:\s*hidden\s*!important/);
  });

  it('openConsoleWindow activates console-window and removes window-minimized', () => {
    const overlay = document.getElementById('console-modal-overlay');
    const modal = document.getElementById('console-window');
    expect(overlay.classList.contains('open')).toBe(false);

    openConsoleWindow();

    expect(overlay.classList.contains('open')).toBe(true);
    expect(overlay.classList.contains('window-minimized')).toBe(false);
    expect(modal.classList.contains('window-minimized')).toBe(false);
  });
});
