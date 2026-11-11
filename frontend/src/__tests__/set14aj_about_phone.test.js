import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";

describe("About & Updates on a phone (SET-14, Settings finding 24)", () => {
  it("the channel row and chooser wrap instead of pushing the pane wider than the screen", () => {
    const css = readFileSync("frontend/src/styles/60-mgmt-window.css", "utf8");
    expect(css).toMatch(/#mgmt-pane-about \.ab-row-5 \{[^}]*flex-wrap: wrap/);
    expect(css).toMatch(/#mgmt-pane-about \.ab-row-xs-box \{[^}]*flex-wrap: wrap/);
  });
});
