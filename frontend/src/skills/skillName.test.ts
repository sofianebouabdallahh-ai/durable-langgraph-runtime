import { describe, expect, it } from "vitest";

import { skillName } from "./SkillsPage";

describe("a skill's name, as people type it", () => {
  it("follows the Agent Skills rule", () => {
    expect(skillName("Trip checklist!")).toBe("trip-checklist");
    expect(skillName("  --Weekly  Update--  ")).toBe("weekly-update");
    expect(skillName("2026 plans")).toBe("2026-plans");
    expect(skillName("x".repeat(80))).toHaveLength(64);
    expect(skillName("!!!")).toBe("");
  });
});
