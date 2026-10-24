import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../toast.js", () => ({ showConfirmToast: vi.fn(), showToast: vi.fn() }));

import { showConfirmToast } from "../toast.js";
import { isStaleBuildError, offerReload, installStaleBuildGuard, _resetStaleBuildForTesting } from "../stale-build.js";

describe("page older than an update", () => {
  beforeEach(() => {
    _resetStaleBuildForTesting();
    showConfirmToast.mockClear();
  });

  it("recognises failed module downloads in each browser", () => {
    expect(isStaleBuildError(new TypeError("Failed to fetch dynamically imported module: /assets/x-1.js"))).toBe(true); // Chrome
    expect(isStaleBuildError(new TypeError("Importing a module script failed."))).toBe(true); // Safari
    expect(isStaleBuildError(new TypeError("error loading dynamically imported module: /assets/x.js"))).toBe(true); // Firefox
    expect(isStaleBuildError(new Error("Unauthorized"))).toBe(false);
    expect(isStaleBuildError(null)).toBe(false);
  });

  it("offers a reload once a minute, and Reload reloads", () => {
    const win = { location: { reload: vi.fn() } };
    expect(offerReload(win)).toBe(true);
    expect(offerReload(win)).toBe(false);
    expect(showConfirmToast).toHaveBeenCalledTimes(1);
    showConfirmToast.mock.calls[0][2]();
    expect(win.location.reload).toHaveBeenCalled();
  });

  it("listens for failed loads, not other rejections", () => {
    const handlers = {};
    const win = { addEventListener: (type, fn) => { handlers[type] = fn; }, location: { reload: vi.fn() } };
    installStaleBuildGuard(win);
    const other = { reason: new Error("boom"), preventDefault: vi.fn() };
    handlers.unhandledrejection(other);
    expect(showConfirmToast).not.toHaveBeenCalled();
    expect(other.preventDefault).not.toHaveBeenCalled();
    const stale = { reason: new TypeError("Importing a module script failed."), preventDefault: vi.fn() };
    handlers.unhandledrejection(stale);
    expect(stale.preventDefault).toHaveBeenCalled();
    expect(showConfirmToast).toHaveBeenCalledTimes(1);
    _resetStaleBuildForTesting();
    const pre = { preventDefault: vi.fn() };
    handlers["vite:preloadError"](pre);
    expect(pre.preventDefault).toHaveBeenCalled();
    expect(showConfirmToast).toHaveBeenCalledTimes(2);
  });
});
