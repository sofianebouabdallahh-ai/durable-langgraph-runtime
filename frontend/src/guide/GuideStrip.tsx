/**
 * The guide on the screen where a step is done (phase L3d): what to do here, in a
 * sentence; a tick and "Next" when the server says it's done. Inline, in reading
 * order, never over anything (no spotlight, no focus trap). "Show me" scrolls to the
 * section and moves focus to it.
 */
import { ArrowRight, Check, Compass, X } from "lucide-react";

import { href } from "../app/route";
import { Button } from "../ui/primitives";
import { guide, ORDER, STEPS, type StepKey, useOnboarding, useOnboardingRefresh } from "./api";

/** Where each step is done in the Studio. */
const SECTION: Partial<Record<StepKey, string>> = { tool: "section-tools", helper: "section-helpers", try: "test-chat" };

function showMe(testId: string) {
  const el = document.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "start" });
  el.setAttribute("tabindex", "-1");
  el.focus({ preventScroll: true });
  el.classList.add("ring-4", "ring-sun-300", "dark:ring-sun-700/60");
  window.setTimeout(() => {
    el.classList.remove("ring-4", "ring-sun-300", "dark:ring-sun-700/60");
  }, 2500);
}

/** `steps`: the steps this screen is for (the strip shows the first one not done). */
export function GuideStrip({ steps, agentId }: { steps: readonly StepKey[]; agentId?: string }) {
  const state = useOnboarding();
  const refresh = useOnboardingRefresh();
  const s = state.data;
  if (!s || s.dismissed || s.finished) return null;
  if (agentId !== undefined && s.agent?.id !== agentId) return null; // another agent: not the guide's
  const status = (k: StepKey) => s.steps.find((x) => x.key === k);
  const here = steps.find((k) => status(k)?.done !== true && status(k)?.skipped !== true);
  const n = (k: StepKey) => ORDER.indexOf(k) + 1;
  const section = here ? SECTION[here] : undefined;
  return (
    <section
      aria-label="Getting started"
      data-testid="guide-strip"
      className="flex flex-wrap items-center gap-3 rounded-2xl bg-sun-50 px-4 py-3 text-sm ring-1 ring-sun-200 dark:bg-sun-700/10 dark:ring-sun-700/40"
    >
      <Compass aria-hidden className="size-5 shrink-0 text-sun-700 dark:text-sun-300" />
      {here ? (
        <p className="min-w-0 flex-1">
          <strong>
            Step {n(here)} of {ORDER.length} · {STEPS[here].title}.
          </strong>{" "}
          {STEPS[here].here}
        </p>
      ) : (
        <p className="min-w-0 flex-1">
          <Check aria-hidden className="mr-1 inline size-4 text-emerald-600" />
          <strong>Done here.</strong> {s.next ? `Next: ${STEPS[s.next].title.toLowerCase()}.` : ""}
        </p>
      )}
      {section && (
        <Button size="sm" onClick={() => { showMe(section); }}>
          Show me
        </Button>
      )}
      <a href={href({ page: "start" })} className="inline-flex items-center gap-1 font-medium text-sun-800 hover:underline dark:text-sun-200">
        {here ? "The guide" : "Next step"} <ArrowRight aria-hidden className="size-3.5" />
      </a>
      <button
        type="button"
        aria-label="Hide the guide"
        className="rounded-lg p-1 text-stone-500 hover:bg-sun-100 dark:hover:bg-stone-800"
        onClick={() => { void guide.update({ dismissed: true }).then(refresh); }}
      >
        <X aria-hidden className="size-4" />
      </button>
    </section>
  );
}
