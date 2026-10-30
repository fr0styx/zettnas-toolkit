import { describe, it, expect, vi } from "vitest";

vi.mock("../i18n.js", async (orig) => ({ ...(await orig()), getLanguage: () => "de" }));

import { explain } from "../error-text.js";

describe("errors say their real cause in every language (NUX-1)", () => {
  it("a wrong folder password is not a name clash", () => {
    const msg = explain("That password is wrong.", "wrong_password", { code: 409 });
    expect(msg).not.toMatch(/another name|andere/i);
  });

  it("each new slug has its own sentence", () => {
    for (const slug of ["wrong_password", "folder_busy", "already_running", "not_ready"]) {
      expect(explain("x", slug, { code: 409 })).not.toBe(explain("x", "conflict", { code: 409 }));
    }
  });
});
