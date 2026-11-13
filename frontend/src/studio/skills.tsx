/**
 * Skills in the Studio (phase L3c): attach skills from the library to the agent or a
 * helper, and "Improve my instructions" (the instructions coach's suggestion, shown
 * next to yours: you choose).
 */
import { BookOpen, Check, Code2, Wand2, X } from "lucide-react";
import { type Dispatch, useState } from "react";

import { href } from "../app/route";
import { problemText } from "../chat/problems";
import { SCAN_LABEL, type Skill, useSkills } from "../skills/api";
import { Dialog, Issues, Section, Switch } from "../ui/form";
import { Button, Pill, Spinner } from "../ui/primitives";
import { type InstructionsProposal, studio, useAssist } from "./api";
import { type AgentDocument, type Edit, type Issue, issuesFor } from "./editor";

/** The skills attached to one agent or helper, and a way to add more from the library.
 * Each can be "Always use": in its instructions every turn instead of loaded when needed
 * (small models rarely load skills themselves). A skill whose scan found something to
 * check is attached only after a confirmation. */
export function SkillPicker({
  label,
  value,
  always,
  onChange,
  issues,
  readOnly,
}: {
  label: string;
  value: readonly string[];
  always: readonly string[];
  onChange: (skills: string[], always: string[]) => void;
  issues: readonly Issue[];
  readOnly: boolean;
}) {
  const library = useSkills();
  const [confirming, setConfirming] = useState<Skill | null>(null);
  // A fresh picker after each choice: picking the same skill again after a Cancel must
  // still count as a choice (a controlled <select> could swallow it).
  const [picks, setPicks] = useState(0);
  const byName = new Map((library.data ?? []).map((s) => [s.name, s]));
  const available = (library.data ?? []).filter((s) => !value.includes(s.name));
  // Attached skills nobody has read yet (H10): used as data until then, so said, not blocked.
  const unread = value.filter((n) => byName.get(n)?.approved === false);
  const attach = (name: string) => {
    onChange([...value, name], [...always]);
  };
  return (
    <div data-testid="skill-picker">
      <div className="mb-1.5 text-sm font-medium">{label}</div>
      {value.length === 0 && <p className="text-sm text-stone-500">None yet.</p>}
      <ul className="space-y-2">
        {value.map((name) => (
          <AttachedSkill
            key={name}
            name={name}
            skill={byName.get(name)}
            readOnly={readOnly}
            always={always.includes(name)}
            onAlways={(on) => {
              onChange([...value], on ? [...always.filter((n) => n !== name), name] : always.filter((n) => n !== name));
            }}
            onRemove={() => {
              onChange(value.filter((n) => n !== name), always.filter((n) => n !== name));
            }}
          />
        ))}
      </ul>
      {unread.length > 0 && (
        <p className="mt-2 text-xs text-amber-800 dark:text-amber-300" data-testid="skills-unread">
          {unread.length === 1 ? "1 skill waits" : `${String(unread.length)} skills wait`} for your review: used as data until you've read{" "}
          {unread.length === 1 ? "it" : "them"} on the{" "}
          <a href={href({ page: "skills" })} className="underline">
            Skills page
          </a>
          .
        </p>
      )}
      {!readOnly && (
        <label className="mt-2 block text-sm">
          <span className="sr-only">Add a skill to {label.toLowerCase()}</span>
          <select
            key={picks}
            defaultValue=""
            disabled={available.length === 0}
            onChange={(e) => {
              setPicks((n) => n + 1);
              const skill = byName.get(e.target.value);
              if (!skill) return;
              if (skill.scan.status === "clean") attach(skill.name);
              else setConfirming(skill); // "Needs a look": say what the scan found first
            }}
            className="w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-[15px] dark:border-stone-700 dark:bg-stone-950"
          >
            <option value="">{available.length ? "Add a skill…" : library.data?.length ? "Every skill is attached" : "No skills yet"}</option>
            {available.map((s) => (
              <option key={s.id} value={s.name}>
                {s.name}: {s.description.slice(0, 80)}
                {s.scan.status !== "clean" ? ` (${SCAN_LABEL[s.scan.status].label.toLowerCase()})` : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      <Issues issues={issues} />
      <p className="mt-1.5 text-xs text-stone-500">
        Write or upload skills on the{" "}
        <a href={href({ page: "skills" })} className="underline">
          Skills page
        </a>
        . The agent loads one when it needs it, or every time with Always use.
      </p>
      <Dialog
        open={confirming !== null}
        onClose={() => {
          setConfirming(null);
        }}
        title={`Attach “${confirming?.name ?? ""}”?`}
      >
        {confirming && (
          <div className="space-y-3 text-sm" data-testid="skill-confirm">
            <p>
              Its check found {confirming.scan.findings.length === 1 ? "something" : "a few things"} worth a look. The agent reads skills as information,
              never as orders, but make sure this is the skill you mean.
            </p>
            <ul className="space-y-1.5">
              {confirming.scan.findings.map((f, i) => (
                <li key={i} className="flex gap-2 rounded-lg bg-amber-50 px-3 py-2 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                  <span aria-hidden>⚠</span>
                  <span>
                    {f.message}
                    {f.where && <span className="text-amber-700/80 dark:text-amber-300/70"> ({f.where})</span>}
                  </span>
                </li>
              ))}
            </ul>
            <div className="flex justify-end gap-2 pt-1">
              <Button
                onClick={() => {
                  setConfirming(null);
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={confirming.scan.status === "blocked"}
                onClick={() => {
                  attach(confirming.name);
                  setConfirming(null);
                }}
              >
                Attach anyway
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}

function AttachedSkill({
  name,
  skill,
  readOnly,
  always,
  onAlways,
  onRemove,
}: {
  name: string;
  skill: Skill | undefined;
  readOnly: boolean;
  always: boolean;
  onAlways: (on: boolean) => void;
  onRemove: () => void;
}) {
  const scan = skill ? SCAN_LABEL[skill.scan.status] : null;
  return (
    <li className="flex items-start gap-3 rounded-xl border border-stone-200 px-3 py-2 dark:border-stone-700" data-testid="attached-skill">
      <BookOpen aria-hidden className="mt-0.5 size-4 shrink-0 text-sun-600" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[13px] font-medium">{name}</span>
          {!skill && <Pill tone="rose">Not in the library</Pill>}
          {scan && skill?.scan.status !== "clean" && <Pill tone={scan.tone}>{scan.label}</Pill>}
          {skill && !skill.approved && <Pill tone="amber">Waits for your review</Pill>}
          {skill?.files.some((f) => f.kind === "script") && (
            <Pill tone="amber">
              <Code2 aria-hidden className="size-3" /> Has code: never runs
            </Pill>
          )}
        </div>
        {skill && <p className="text-xs text-stone-500">{skill.description}</p>}
        <div className="mt-2">
          <Switch
            checked={always}
            disabled={readOnly}
            onChange={onAlways}
            label={`Always use ${name}`}
            description={always ? "In its instructions every time." : "Loaded when a request needs it."}
          />
        </div>
      </div>
      {!readOnly && (
        <button type="button" aria-label={`Remove ${name}`} onClick={onRemove} className="rounded-lg p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700 dark:hover:bg-stone-800">
          <X aria-hidden className="size-4" />
        </button>
      )}
    </li>
  );
}

export function SkillsSection({ doc, issues, dispatch, readOnly }: { doc: AgentDocument; issues: readonly Issue[]; dispatch: Dispatch<Edit>; readOnly: boolean }) {
  return (
    <Section
      title="Skills"
      description="Know-how it loads when a task needs it. Each helper can have its own."
      icon={<BookOpen aria-hidden className="size-4" />}
      testId="section-skills"
    >
      <SkillPicker
        label="Its skills"
        value={doc.skills ?? []}
        always={doc.always_skills ?? []}
        readOnly={readOnly}
        issues={issuesFor(issues, "agent", ["skills", "always_skills"])}
        onChange={(value, always) => {
          dispatch({ kind: "skills", value, always });
        }}
      />
    </Section>
  );
}

/** "Improve my instructions": ask the coach, then compare and choose. Nothing changes until you accept. */
export function ImproveInstructions({
  agentId,
  current,
  disabled,
  onAccept,
}: {
  agentId: string;
  current: string;
  disabled: boolean;
  onAccept: (instructions: string) => void;
}) {
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const answer = useAssist(runId);
  const close = () => {
    setRunId(null);
  };
  const result = answer.data;
  const proposal = result?.status === "done" ? (result.proposal as unknown as InstructionsProposal) : null;
  const changed = proposal !== null && proposal.instructions.trim() !== current.trim();
  return (
    <>
      <Button
        size="sm"
        disabled={disabled}
        onClick={() => {
          setError(null);
          studio
            .improve(agentId)
            .then((r) => {
              setRunId(r.run_id);
            })
            .catch((e: unknown) => {
              setError(problemText(e));
            });
        }}
      >
        <Wand2 aria-hidden className="size-4" /> Improve my instructions
      </Button>
      {error && (
        <span role="alert" className="text-xs text-rose-600">
          {error}
        </span>
      )}
      <Dialog open={runId !== null} onClose={close} title="Suggested instructions" wide>
        {(!result || result.status === "working") && <Spinner label="Reading your instructions…" />}
        {result?.status === "failed" && (
          <div role="alert" className="text-sm text-rose-700 dark:text-rose-400">
            {result.problem}
          </div>
        )}
        {proposal && (
          <div className="space-y-3" data-testid="improve-suggestion">
            <p className="text-sm text-stone-600 dark:text-stone-400">{proposal.what_changed}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Compare title="Yours" text={current} />
              <Compare title="Suggested" text={proposal.instructions} highlight />
            </div>
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={close}>{changed ? "Keep mine" : "Close"}</Button>
          {changed && (
            <Button
              variant="primary"
              onClick={() => {
                onAccept(proposal.instructions);
                close();
              }}
            >
              <Check aria-hidden className="size-4" /> Use the suggestion
            </Button>
          )}
        </div>
      </Dialog>
    </>
  );
}

function Compare({ title, text, highlight = false }: { title: string; text: string; highlight?: boolean }) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold tracking-wide text-stone-500 uppercase">{title}</div>
      <pre
        className={`max-h-72 overflow-auto rounded-xl p-3 text-[13px] leading-relaxed whitespace-pre-wrap ${highlight ? "bg-sun-50 ring-1 ring-sun-200 dark:bg-sun-700/10 dark:ring-sun-700/40" : "bg-stone-50 dark:bg-stone-950"}`}
      >
        {text}
      </pre>
    </div>
  );
}
