import { describe, it, expect, vi, afterEach } from "vitest";

// PERF-9: a German user doesn't download the English strings unless one is missing
describe("English only for missing keys (PERF-9)", () => {
  afterEach(() => {
    localStorage.removeItem("zettnas_language");
    vi.resetModules();
  });

  it("loads only the saved language at start, and English on the first missing key", async () => {
    vi.resetModules();
    localStorage.setItem("zettnas_language", "de");
    const m = await import("../i18n.js");
    await m.setLanguage("de");
    expect(m.TRANSLATIONS.de).toBeDefined();
    expect(m.TRANSLATIONS.en).toBeUndefined();
    expect(m.t("fm.search_results", "Found {count} item(s)", { count: 2 })).toBe("2 Element(e) gefunden");
    expect(m.TRANSLATIONS.en).toBeUndefined(); // a key German has: still no English
    expect(m.t("no.such.key", "Fallback text")).toBe("Fallback text");
    await vi.waitFor(() => expect(m.TRANSLATIONS.en).toBeDefined());
  });

  it("an English user gets English at start", async () => {
    vi.resetModules();
    localStorage.setItem("zettnas_language", "en");
    const m = await import("../i18n.js");
    await vi.waitFor(() => expect(m.TRANSLATIONS.en).toBeDefined());
  });
});
