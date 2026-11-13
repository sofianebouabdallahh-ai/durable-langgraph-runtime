/** The skill library (phase L3c): server state and commands. */
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, type Schemas, unwrap } from "../api/client";

export type Skill = Schemas["SkillView"];
export type SkillDetail = Schemas["SkillDetail"];
export type Saved = Schemas["SavedView"];
export type Finding = Schemas["Finding"];
export type ScanStatus = Schemas["ScanView"]["status"];

export const skillKeys = { all: ["skills"] as const, one: (id: string) => ["skills", id] as const };

export function useSkills() {
  return useQuery({ queryKey: skillKeys.all, queryFn: () => unwrap(api.GET("/skills")) });
}

export function useSkill(id: string | null) {
  return useQuery({
    queryKey: skillKeys.one(id ?? ""),
    queryFn: () => unwrap(api.GET("/skills/{skill_id}", { params: { path: { skill_id: id ?? "" } } })),
    enabled: id !== null,
  });
}

export function useSkillsRefresh() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: skillKeys.all });
    void client.invalidateQueries({ queryKey: ["studio"] }); // drafts that use a skill may be untested now
  };
}

/** The raw file is the body (no multipart), like agent imports. */
async function sendFile(url: string, file: File): Promise<Saved> {
  const response = await fetch(`${url}?filename=${encodeURIComponent(file.name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: file,
  });
  const body = (await response.json()) as Saved & { detail?: string; type?: string };
  if (!response.ok) throw new ApiError(response.status, body);
  return body;
}

export const skills = {
  create: (body: Schemas["NewSkill"]) => unwrap(api.POST("/skills", { body })),
  edit: (id: string, body: Schemas["EditSkill"]) => unwrap(api.PATCH("/skills/{skill_id}", { params: { path: { skill_id: id } }, body })),
  upload: (file: File) => sendFile("/api/skills/upload", file),
  replace: (id: string, file: File) => sendFile(`/api/skills/${encodeURIComponent(id)}/upload`, file),
  /** "I've read this": the current version may be plain text in prompts (H10). Idempotent. */
  approve: (id: string) => unwrap(api.POST("/skills/{skill_id}/approve", { params: { path: { skill_id: id } } })),
  archive: (id: string) => api.DELETE("/skills/{skill_id}", { params: { path: { skill_id: id } } }),
  exportUrl: (id: string) => `/api/skills/${encodeURIComponent(id)}/export`,
  fileUrl: (id: string, path: string) => `/api/skills/${encodeURIComponent(id)}/files/${path.split("/").map(encodeURIComponent).join("/")}`,
};

/** What a failed save says: the standard's issues, or the scan's findings, in plain words. */
export function saveProblems(e: unknown): string[] {
  if (!(e instanceof ApiError)) return ["Couldn't reach the server. Check that Nuria is running."];
  const issues = e.extra.issues as { message: string; blocking: boolean }[] | undefined;
  if (issues?.length) return issues.filter((i) => i.blocking).map((i) => i.message);
  const scan = e.extra.scan as { findings: Finding[] } | undefined;
  if (scan) return scan.findings.filter((f) => f.severity === "block").map((f) => (f.where ? `${f.message} (${f.where})` : f.message));
  return [e.message];
}

export const SCAN_LABEL: Record<ScanStatus, { label: string; tone: "green" | "amber" | "rose" }> = {
  clean: { label: "Clean", tone: "green" },
  review: { label: "Needs a look", tone: "amber" },
  blocked: { label: "Blocked", tone: "rose" },
};
