/** Which model answers, at the foot of the sidebar; how to change it. */
import { useQuery } from "@tanstack/react-query";
import { Cpu, Sparkles } from "lucide-react";

import { api, unwrap } from "../api/client";

export function useAbout() {
  return useQuery({ queryKey: ["about"], queryFn: () => unwrap(api.GET("/about")), staleTime: Infinity });
}

export function ModelStatus() {
  const about = useAbout();
  if (!about.data) return null;
  const demo = about.data.demo_model;
  return (
    <div className="border-t border-stone-200 p-3 dark:border-stone-800">
      <div
        className="flex items-center gap-2.5 rounded-xl px-2 py-1.5"
        data-testid="model-status"
        title={demo ? "Connect a real model: ./setup.sh --model ollama (or openai, foundry)" : `Answers come from ${about.data.model_provider}`}
      >
        <span className={`flex size-7 items-center justify-center rounded-lg ${demo ? "bg-sun-100 text-sun-700 dark:bg-sun-700/20 dark:text-sun-300" : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"}`}>
          {demo ? <Sparkles aria-hidden className="size-3.5" /> : <Cpu aria-hidden className="size-3.5" />}
        </span>
        <span className="min-w-0 leading-tight">
          <span className="block truncate text-[13px] font-medium text-stone-800 dark:text-stone-200">
            {demo ? "Demo model" : (about.data.chat_model ?? about.data.model_provider)}
          </span>
          <span className="block truncate text-xs text-stone-500">{demo ? "Offline · follows simple rules" : `via ${about.data.model_provider}`}</span>
        </span>
      </div>
    </div>
  );
}
