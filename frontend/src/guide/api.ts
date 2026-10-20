/** Getting started (phase L3d): progress is derived on the server; these are its words. */
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "../api/client";

export type Onboarding = Schemas["OnboardingView"];
export type StepKey = Onboarding["steps"][number]["key"];

export function useOnboarding() {
  return useQuery({ queryKey: ["onboarding"], queryFn: () => unwrap(api.GET("/onboarding")) });
}

export function useOnboardingRefresh() {
  const client = useQueryClient();
  return (state?: Onboarding) => {
    if (state) client.setQueryData(["onboarding"], state);
    void client.invalidateQueries({ queryKey: ["onboarding"] });
  };
}

export const guide = {
  update: (body: Partial<Schemas["OnboardingUpdate"]>) => unwrap(api.PUT("/onboarding", { body: { restart: false, ...body } })),
};

/** Each step: its title, why it matters (one sentence), and what to do on the screen it opens. */
export const STEPS: Record<StepKey, { title: string; why: string; here: string }> = {
  model: {
    title: "Choose a model",
    why: "The AI your agents think with: a free one on this computer, or a hosted one with your key.",
    here: "Add a model and make it the default: Nuria tests that it answers and can use tools.",
  },
  agent: {
    title: "Create your agent",
    why: "Describe the assistant you want in a few sentences, and Nuria drafts it for you.",
    here: "Describe it, or start from a template.",
  },
  tool: {
    title: "Give it a tool",
    why: "Tools are what it can use: search, a calculator, notes, notifications (which always ask you first).",
    here: "In Tools, switch on one it needs. It saves by itself.",
  },
  helper: {
    title: "Give it a helper",
    why: "A helper is another agent yours can hand part of a job to, so the parts are done in parallel.",
    here: "In Helpers, type a name (e.g. “Restaurant finder”), Add helper, then say what it does.",
  },
  try: {
    title: "Try it, then publish",
    why: "Chat with your draft first; publishing makes it available to everyone, as a version that won't change.",
    here: "Start a test chat on the right and send a message. Then Publish, and Chat with it.",
  },
};

export const ORDER: readonly StepKey[] = ["model", "agent", "tool", "helper", "try"];

export function doneCount(state: Onboarding): number {
  return state.steps.filter((s) => s.done || s.skipped).length;
}
