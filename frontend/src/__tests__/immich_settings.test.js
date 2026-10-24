import { describe, it, expect } from "vitest";
import { immichResultsHtml, settingsHtml } from "../components/immich-settings.js";

describe("Immich in ZettNAS (Batch 6)", () => {
  it("shows Immich photos with thumbnails that go through ZettNAS", () => {
    document.body.innerHTML = immichResultsHtml([{ id: "a1", name: "beach.jpg", thumbnail_url: "/api/immich/thumbnail/a1", immich_url: "http://immich/photos/a1" }]);
    expect(document.querySelector("img").getAttribute("src")).toBe("/api/immich/thumbnail/a1");
    expect(immichResultsHtml([])).toBe("");
  });

  it("lets administrators set the address and each person connect their own key", () => {
    document.body.innerHTML = settingsHtml({ url: "", detected: "http://10.0.0.5:2283", connected: false }, true);
    expect(document.querySelector("[data-immich-url] input").value).toBe("http://10.0.0.5:2283");
    expect(document.querySelector("[data-immich-key] button").disabled).toBe(true);
    document.body.innerHTML = settingsHtml({ url: "http://immich", connected: true }, false);
    expect(document.querySelector("[data-immich-url]")).toBeNull();
    expect(document.querySelector("[data-immich-disconnect]")).not.toBeNull();
  });
});
