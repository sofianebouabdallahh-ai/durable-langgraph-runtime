/** Home's invitation to Getting started (phase L3d): offered, never started by itself. */
import { Compass } from "lucide-react";

import { type Route } from "../app/route";
import { Button } from "../ui/primitives";
import { doneCount, guide, useOnboarding, useOnboardingRefresh } from "./api";

export function GuideCard({ go }: { go: (route: Route) => void }) {
  const state = useOnboarding();
  const refresh = useOnboardingRefresh();
  const s = state.data;
  if (!s || s.finished || s.dismissed) return null;
  const count = doneCount(s);
  return (
    <section aria-label="Getting started" data-testid="guide-card" className="mb-6 flex flex-wrap items-center gap-4 rounded-2xl bg-white p-4 shadow-soft ring-1 ring-sun-200 dark:bg-stone-900 dark:ring-sun-700/40">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-sun-100 text-sun-700 dark:bg-sun-700/20 dark:text-sun-300">
        <Compass aria-hidden className="size-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium">{count === 0 ? "New here? Build your first agent in 5 steps" : `Your first agent: ${String(count)} of 5 steps done`}</p>
        <p className="text-sm text-stone-500 dark:text-stone-400">Choose a model, describe your agent, give it a tool and a helper, then try it.</p>
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="ghost" onClick={() => { void guide.update({ dismissed: true }).then(refresh); }}>
          Not now
        </Button>
        <Button size="sm" variant="primary" onClick={() => { go({ page: "start" }); }}>
          {count === 0 ? "Get started" : "Continue"}
        </Button>
      </div>
    </section>
  );
}
