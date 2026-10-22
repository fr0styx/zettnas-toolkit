import { describe, it, expect } from "vitest";
import { TRANSLATIONS, getLanguage, loadLanguage, setLanguage, t } from "../i18n.js";
import de from "../locales/de.js";

describe("per-language files (FE-03)", () => {
  it("ships English only until another language is used", async () => {
    expect(Object.keys(TRANSLATIONS)).toContain("en");
    expect(await loadLanguage("xx")).toBe(false);
    await setLanguage("de");
    expect(getLanguage()).toBe("de");
    expect(TRANSLATIONS.de).toBe(de);
    const key = Object.keys(de).find((k) => de[k] !== TRANSLATIONS.en[k]);
    expect(t(key)).toBe(de[key]);
    await setLanguage("en");
  });

  it("falls back to English for unknown languages", async () => {
    await setLanguage("klingon");
    expect(getLanguage()).toBe("en");
  });
});

describe("toasts are translated (FE-13)", () => {
  it("shows a converted toast in German with its value filled in", async () => {
    await setLanguage("de");
    expect(t("toast.trash_emptied_storage_reclaimed", "Trash emptied. Storage reclaimed.")).toBe("Papierkorb geleert, Speicher freigegeben.");
    expect(t("toast.failed_to_empty_trash", "Failed to empty trash: {message}", { message: "Zugriff verweigert" }))
      .toBe("Papierkorb konnte nicht geleert werden: Zugriff verweigert");
    await setLanguage("en");
  });
});
