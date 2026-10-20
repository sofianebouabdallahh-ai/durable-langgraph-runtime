/**
 * Skills (phase L3c, CR-006 R17.4): reusable know-how agents load when they need it.
 * Write one here, or upload one in the Agent Skills format (a zip of its folder, or
 * a SKILL.md). Every save is checked and scanned, and the report says what was found
 * in plain words. Agents see a skill's name and "when to use it" until they load it.
 */
import { AlertTriangle, BookOpen, CheckCircle2, ChevronDown, Code2, Download, FileText, Pencil, Plus, ShieldAlert, Trash2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";

import { Dialog, TextArea, TextField } from "../ui/form";
import { Button, Pill, Spinner } from "../ui/primitives";
import { type Finding, SCAN_LABEL, type Saved, type Skill, saveProblems, skills, useSkill, useSkills, useSkillsRefresh } from "./api";

const WARN_TOKENS = 5_000;

export function SkillsPage() {
  const library = useSkills();
  const refresh = useSkillsRefresh();
  const [editing, setEditing] = useState<{ skill: Skill | null } | null>(null);
  const [result, setResult] = useState<{ title: string; saved?: Saved; problems?: string[] } | null>(null);
  const file = useRef<HTMLInputElement>(null);

  const upload = async (f: File) => {
    setResult(null);
    try {
      const saved = await skills.upload(f);
      refresh();
      setResult({ title: `Added “${saved.skill.name}”`, saved });
    } catch (e) {
      setResult({ title: `“${f.name}” wasn't added`, problems: saveProblems(e) });
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <div className="flex flex-wrap items-end gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-4xl font-medium tracking-tight">Skills</h1>
          <p className="mt-2 max-w-2xl text-stone-500 dark:text-stone-400">
            Know-how your agents load when a task needs it: a checklist, a house style, how to do something well. Attach skills to an agent or a
            helper in the Studio.
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => file.current?.click()}>
            <Upload aria-hidden className="size-4" /> Upload
          </Button>
          <input
            ref={file}
            type="file"
            accept=".zip,.md"
            className="hidden"
            aria-label="Upload a skill"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void upload(f);
              e.target.value = "";
            }}
          />
          <Button
            variant="primary"
            onClick={() => {
              setEditing({ skill: null });
            }}
          >
            <Plus aria-hidden className="size-4" /> New skill
          </Button>
        </div>
      </div>

      {result && (
        <SaveResult
          {...result}
          onClose={() => {
            setResult(null);
          }}
        />
      )}

      <div className="mt-8 space-y-4">
        {library.isPending && <Spinner label="Loading skills…" />}
        {library.data?.length === 0 && (
          <div className="rounded-2xl border border-dashed border-stone-300 p-8 text-center dark:border-stone-700">
            <p className="font-display text-xl">Write your first skill</p>
            <p className="mt-1 text-sm text-stone-500">For example, how your team writes a weekly update.</p>
          </div>
        )}
        {library.data?.map((s) => (
          <SkillCard
            key={s.id}
            skill={s}
            onEdit={() => {
              setEditing({ skill: s });
            }}
            onReplaced={(saved) => {
              setResult({ title: `Updated “${saved.skill.name}”`, saved });
            }}
            onFailed={(title, problems) => {
              setResult({ title, problems });
            }}
          />
        ))}
      </div>

      <SkillDialog
        key={editing?.skill?.id ?? "new"}
        open={editing !== null}
        skill={editing?.skill ?? null}
        onClose={() => {
          setEditing(null);
        }}
        onSaved={(saved, created) => {
          setEditing(null);
          setResult({ title: created ? `Added “${saved.skill.name}”` : `Saved “${saved.skill.name}”`, saved });
        }}
      />
    </div>
  );
}

/** What a save or upload produced: the scan's verdict and any warnings, or why it failed. */
function SaveResult({ title, saved, problems, onClose }: { title: string; saved?: Saved; problems?: string[]; onClose: () => void }) {
  const failed = problems !== undefined;
  const findings = saved?.skill.scan.findings ?? [];
  const warnings = saved?.warnings ?? [];
  return (
    <div
      role={failed ? "alert" : "status"}
      data-testid="skill-result"
      className={`mt-6 rounded-2xl p-4 ring-1 ${failed ? "bg-rose-50 ring-rose-200 dark:bg-rose-950/40 dark:ring-rose-900" : "bg-white ring-stone-200 dark:bg-stone-900 dark:ring-stone-800"}`}
    >
      <div className="flex items-start gap-2">
        {failed ? <ShieldAlert aria-hidden className="mt-0.5 size-5 text-rose-600" /> : <CheckCircle2 aria-hidden className="mt-0.5 size-5 text-emerald-600" />}
        <div className="min-w-0 flex-1">
          <p className="font-medium">{title}</p>
          {failed && (
            <ul className="mt-1 list-disc pl-5 text-sm text-rose-800 dark:text-rose-200">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          {saved && <p className="mt-0.5 text-sm text-stone-600 dark:text-stone-400">{scanSentence(saved.skill.scan.status)}</p>}
          {findings.length > 0 && <Findings findings={findings} />}
          {warnings.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-sm text-amber-800 dark:text-amber-300">
              {warnings.map((w) => (
                <li key={w.message}>{w.message}</li>
              ))}
            </ul>
          )}
        </div>
        <button type="button" aria-label="Dismiss" onClick={onClose} className="rounded-lg p-1 text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800">
          <X aria-hidden className="size-4" />
        </button>
      </div>
    </div>
  );
}

function scanSentence(status: Skill["scan"]["status"]): string {
  if (status === "clean") return "The scan found nothing to worry about.";
  if (status === "review") return "Saved. The scan found things worth a look:";
  return "The scan blocked it.";
}

function Findings({ findings }: { findings: readonly Finding[] }) {
  return (
    <ul className="mt-2 space-y-1.5" data-testid="scan-findings">
      {findings.map((f, i) => (
        <li key={`${f.check}-${String(i)}`} className="flex items-start gap-2 text-sm">
          <AlertTriangle aria-hidden className={`mt-0.5 size-4 shrink-0 ${f.severity === "block" ? "text-rose-600" : "text-amber-600"}`} />
          <span>
            {f.message}
            {f.where && <span className="ml-1 text-xs text-stone-500">({f.where})</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function SkillCard({
  skill,
  onEdit,
  onReplaced,
  onFailed,
}: {
  skill: Skill;
  onEdit: () => void;
  onReplaced: (saved: Saved) => void;
  onFailed: (title: string, problems: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const refresh = useSkillsRefresh();
  const replaceInput = useRef<HTMLInputElement>(null);
  const builtIn = skill.trust === "built_in";
  const hasCode = skill.files.some((f) => f.kind === "script");
  const scan = SCAN_LABEL[skill.scan.status];
  return (
    <article className="rounded-2xl border border-stone-200 bg-white shadow-soft dark:border-stone-800 dark:bg-stone-900" data-testid="skill-card">
      <div className="flex items-start gap-3 p-5">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-sun-50 text-sun-700 dark:bg-sun-700/15 dark:text-sun-300">
          <BookOpen aria-hidden className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-mono text-[15px] font-medium">{skill.name}</h2>
            {builtIn && <Pill tone="blue">Built in</Pill>}
            <Pill tone={scan.tone}>{scan.label}</Pill>
            {hasCode && (
              <Pill tone="amber">
                <Code2 aria-hidden className="size-3" /> Has code: never runs
              </Pill>
            )}
          </div>
          <p className="mt-1 text-sm text-stone-600 dark:text-stone-400">{skill.description}</p>
          <p className="mt-2 text-xs text-stone-500">
            {skill.used_by.length ? `Used by ${skill.used_by.join(", ")}` : "Not used by an agent yet"} · about {skill.tokens.toLocaleString()} tokens
            {skill.files.length > 0 && ` · ${String(skill.files.length)} file${skill.files.length > 1 ? "s" : ""}`}
          </p>
        </div>
        <div className="flex shrink-0 gap-1">
          {!builtIn && (
            <Button size="sm" variant="ghost" onClick={onEdit} aria-label={`Edit ${skill.name}`}>
              <Pencil aria-hidden className="size-4" />
            </Button>
          )}
          <a
            href={skills.exportUrl(skill.id)}
            download
            aria-label={`Download ${skill.name}`}
            className="inline-flex h-8 items-center rounded-xl px-3 text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800"
          >
            <Download aria-hidden className="size-4" />
          </a>
          <Button
            size="sm"
            variant="ghost"
            aria-expanded={open}
            aria-label={open ? "Hide details" : "Show details"}
            onClick={() => {
              setOpen(!open);
            }}
          >
            <ChevronDown aria-hidden className={`size-4 transition ${open ? "rotate-180" : ""}`} />
          </Button>
        </div>
      </div>
      {open && (
        <div className="border-t border-stone-100 p-5 dark:border-stone-800">
          <SkillDetails skill={skill} />
          {!builtIn && (
            <div className="mt-4 flex flex-wrap gap-2">
              <Button size="sm" onClick={() => replaceInput.current?.click()}>
                <Upload aria-hidden className="size-4" /> Upload a new version
              </Button>
              <input
                ref={replaceInput}
                type="file"
                accept=".zip,.md"
                className="hidden"
                aria-label={`Upload a new version of ${skill.name}`}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (!f) return;
                  skills
                    .replace(skill.id, f)
                    .then((saved) => {
                      refresh();
                      onReplaced(saved);
                    })
                    .catch((err: unknown) => {
                      onFailed(`“${f.name}” wasn't saved`, saveProblems(err));
                    });
                }}
              />
              {confirming ? (
                <span className="flex items-center gap-2 text-sm">
                  {skill.used_by.length ? "Published agents keep the version they use. Remove it from the library?" : "Remove it from the library?"}
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => {
                      void skills.archive(skill.id).then(refresh);
                    }}
                  >
                    Remove
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => {
                      setConfirming(false);
                    }}
                  >
                    Keep
                  </Button>
                </span>
              ) : (
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => {
                    setConfirming(true);
                  }}
                >
                  <Trash2 aria-hidden className="size-4" /> Remove
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function SkillDetails({ skill }: { skill: Skill }) {
  const detail = useSkill(skill.id);
  return (
    <div className="space-y-4">
      {skill.scan.findings.length > 0 && (
        <div>
          <h3 className="text-sm font-medium">What the scan found</h3>
          <Findings findings={skill.scan.findings} />
        </div>
      )}
      <div>
        <h3 className="text-sm font-medium">What it teaches</h3>
        {detail.isPending ? (
          <Spinner className="mt-2" />
        ) : (
          <pre className="mt-2 max-h-80 overflow-auto rounded-xl bg-stone-50 p-3 text-[13px] leading-relaxed whitespace-pre-wrap dark:bg-stone-950" data-testid="skill-instructions">
            {detail.data?.instructions}
          </pre>
        )}
      </div>
      {skill.allowed_tools.length > 0 && (
        <p className="text-sm text-stone-600 dark:text-stone-400">
          It asks for: {skill.allowed_tools.join(", ")}. Skills never give an agent tools: the agent's own tools decide.
        </p>
      )}
      {skill.files.length > 0 && (
        <div>
          <h3 className="text-sm font-medium">Files</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {skill.files.map((f) => (
              <li key={f.path} className="flex items-center gap-2">
                {f.kind === "script" ? <Code2 aria-hidden className="size-4 text-amber-600" /> : <FileText aria-hidden className="size-4 text-stone-400" />}
                <a href={skills.fileUrl(skill.id, f.path)} download className="font-mono text-[13px] hover:underline">
                  {f.path}
                </a>
                <span className="text-xs text-stone-500">{formatSize(f.size)}</span>
                {f.kind === "script" && <span className="text-xs text-amber-700 dark:text-amber-400">kept, never run</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1_000) return `${String(bytes)} B`;
  if (bytes < 1_000_000) return `${(bytes / 1_000).toFixed(1)} kB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

/** "Trip checklist!" → "trip-checklist": the standard's name rule, previewed as people type. */
export function skillName(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .replace(/-+$/g, "");
}

function SkillDialog({
  open,
  skill,
  onClose,
  onSaved,
}: {
  open: boolean;
  skill: Skill | null;
  onClose: () => void;
  onSaved: (saved: Saved, created: boolean) => void;
}) {
  const detail = useSkill(skill?.id ?? null);
  const refresh = useSkillsRefresh();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState(skill?.description ?? "");
  const [instructions, setInstructions] = useState<string | null>(null);
  const [notePath, setNotePath] = useState("");
  const [noteText, setNoteText] = useState("");
  const [removed, setRemoved] = useState<string[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const text = instructions ?? detail.data?.instructions ?? "";
  const tokens = text.trim() ? Math.max(1, Math.round(text.length / 4)) : 0;
  const name = skill?.name ?? skillName(title);
  const existing = (skill?.files ?? []).filter((f) => !removed.includes(f.path));

  const save = async () => {
    setSaving(true);
    setProblems([]);
    const files: Record<string, string> = {};
    if (notePath.trim() && noteText.trim()) files[`references/${skillName(notePath) || "notes"}.md`] = noteText;
    try {
      const saved = skill
        ? await skills.edit(skill.id, {
            description,
            instructions: text,
            files: { ...files, ...Object.fromEntries(removed.map((p) => [p, null])) },
          })
        : await skills.create({ name, description, instructions: text, files });
      refresh();
      onSaved(saved, skill === null);
    } catch (e) {
      setProblems(saveProblems(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title={skill ? `Edit ${skill.name}` : "New skill"}>
      <form
        className="max-h-[70vh] space-y-4 overflow-y-auto pr-1"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        {!skill && (
          <TextField
            label="Name"
            value={title}
            required
            maxLength={80}
            autoFocus
            placeholder="Trip checklist"
            hint={name ? `Saved as ${name}` : "Lowercase letters, digits and hyphens"}
            onChange={(e) => {
              setTitle(e.target.value);
            }}
          />
        )}
        <TextArea
          label="When should an agent use it?"
          rows={2}
          maxLength={1024}
          required
          value={description}
          hint="Agents see only this (and the name) until they load the skill, so say what it's for and when."
          placeholder="How to pack for a trip. Use when someone asks what to bring."
          onChange={(e) => {
            setDescription(e.target.value);
          }}
        />
        {skill && detail.isPending ? (
          <Spinner />
        ) : (
          <TextArea
            label="What it should know or do"
            rows={10}
            required
            value={text}
            hint={tokens > WARN_TOKENS ? `About ${tokens.toLocaleString()} tokens: under ${WARN_TOKENS.toLocaleString()} works best.` : tokens ? `About ${tokens.toLocaleString()} token${tokens === 1 ? "" : "s"}.` : "Its steps, rules or checklist, in Markdown."}
            placeholder={"# Packing\n\n- Check the weather first.\n- …"}
            onChange={(e) => {
              setInstructions(e.target.value);
            }}
          />
        )}
        {existing.length > 0 && (
          <div>
            <p className="mb-1.5 text-sm font-medium">Its files</p>
            <ul className="space-y-1">
              {existing.map((f) => (
                <li key={f.path} className="flex items-center gap-2 text-sm">
                  <FileText aria-hidden className="size-4 text-stone-400" />
                  <span className="font-mono text-[13px]">{f.path}</span>
                  <button
                    type="button"
                    className="ml-auto text-xs text-rose-600 hover:underline"
                    onClick={() => {
                      setRemoved([...removed, f.path]);
                    }}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <details className="rounded-xl border border-stone-200 p-3 dark:border-stone-700">
          <summary className="cursor-pointer text-sm font-medium">Add a reference file (optional)</summary>
          <p className="mt-1 text-xs text-stone-500">Longer material the agent reads only when it needs it, e.g. a full checklist.</p>
          <div className="mt-3 space-y-3">
            <TextField
              label="File name"
              value={notePath}
              placeholder="packing-list"
              onChange={(e) => {
                setNotePath(e.target.value);
              }}
            />
            <TextArea
              label="Its text"
              rows={5}
              value={noteText}
              onChange={(e) => {
                setNoteText(e.target.value);
              }}
            />
          </div>
        </details>
        {problems.length > 0 && (
          <ul role="alert" className="list-disc space-y-0.5 pl-5 text-sm text-rose-700 dark:text-rose-400">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={saving || !name || !description.trim() || !text.trim()}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
