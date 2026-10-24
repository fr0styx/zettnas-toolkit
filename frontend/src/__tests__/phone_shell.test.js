import { describe, it, expect, vi } from 'vitest';
import { enablePhoneShell, launcherHtml, tabsHtml, TILES, topPage, tabForPage, updateStatus } from '../components/phone-shell.js';

describe('phone mode (UX-13)', () => {
  it('offers the main places as tiles and five bottom tabs', () => {
    document.body.innerHTML = launcherHtml();
    expect(document.querySelectorAll('[data-phone-open]').length).toBe(TILES().length);
    document.body.innerHTML = tabsHtml();
    expect([...document.querySelectorAll('[data-phone-tab]')].map((b) => b.dataset.phoneTab)).toEqual(['home', 'files', 'apps', 'alerts', 'settings']);
  });

  it('opens places through the deep-link routes and hides the launcher behind a page', () => {
    document.body.innerHTML = '';
    window.openFileManager = vi.fn();
    enablePhoneShell(true);
    expect(document.body.classList.contains('phone-shell')).toBe(true);
    document.querySelector('[data-phone-open="files"]').click();
    expect(window.openFileManager).toHaveBeenCalled();
    enablePhoneShell(false);
    expect(document.getElementById('phone-shell')).toBeNull();
  });
});


describe("phone mode: pages, tabs and status (UX-13)", () => {
  it("does not count a window that is closing or hidden as open", () => {
    document.body.innerHTML = `
      <div class="os-window" id="a" style="z-index: 1001"></div>
      <div class="os-window window-closing" id="b" style="z-index: 1005"></div>
      <div class="os-window" id="c" style="z-index: 1009; opacity: 0"></div>
      <div class="os-window" id="d" aria-hidden="true" style="z-index: 1010"></div>`;
    expect(topPage().id).toBe("a");
    document.getElementById("a").style.display = "none";
    expect(topPage()).toBeNull();
  });

  it("highlights the tab a page belongs to", () => {
    document.body.innerHTML = `<div class="file-manager-window" id="fm"></div><div id="containers-manager-window"></div><div id="management-window"></div>`;
    expect(tabForPage(null)).toBe("home");
    expect(tabForPage(document.getElementById("fm"))).toBe("files");
    expect(tabForPage(document.getElementById("containers-manager-window"))).toBe("apps");
    expect(tabForPage(document.getElementById("management-window"))).toBe("home");
  });

  it("shows Back and the right tab as pages open and close, without polling", async () => {
    document.body.innerHTML = "";
    window.openManagementSection = vi.fn(() => {
      const w = document.createElement("div");
      w.id = "management-window";
      w.style.zIndex = "1000";
      document.body.appendChild(w);
    });
    enablePhoneShell(true);
    document.querySelector("[data-phone-tab=\"settings\"]").click();
    await new Promise((r) => setTimeout(r, 40));
    expect(document.getElementById("phone-back").hidden).toBe(false);
    expect(document.querySelector(".phone-tab.is-current").dataset.phoneTab).toBe("settings");
    expect(document.body.classList.contains("phone-page-open")).toBe(true);
    document.getElementById("management-window").style.display = "none";
    await new Promise((r) => setTimeout(r, 40));
    expect(document.getElementById("phone-back").hidden).toBe(true);
    expect(document.querySelector(".phone-tab.is-current").dataset.phoneTab).toBe("home");
    enablePhoneShell(false);
  });

  it("the launcher shows the live status numbers", () => {
    document.body.innerHTML = launcherHtml();
    updateStatus({ cpu: { util: 12.4, temp: 48 }, mem: { pct: 33 }, storage: { used: "4TB", total: "8TB" }, net: { rx_bytes_sec: 2048, tx_bytes_sec: 3 * 1048576 } });
    const val = (k) => document.querySelector(`[data-phone-stat="${k}"]`).textContent;
    expect(val("cpu")).toBe("12% · 48°C");
    expect(val("ram")).toBe("33%");
    expect(val("storage")).toBe("4TB / 8TB");
    expect(val("net")).toBe("↓ 2 KB/s ↑ 3.0 MB/s");
  });
});
