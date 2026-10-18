/** Which model answers, at the foot of the sidebar; how to change it. */
import { useQuery } from "@tanstack/react-query";
import { Activity, Cpu, Sparkles } from "lucide-react";

import { api, unwrap } from "../api/client";

export function useAbout() {
  return useQuery({ queryKey: ["about"], queryFn: () => unwrap(api.GET("/about")), staleTime: Infinity });
}

export function ModelStatus() {
  const about = useAbout();
  const chosen = useQuery({ queryKey: ["models", "default"], queryFn: () => unwrap(api.GET("/models/default")) });
  if (!about.data) return null;
  const custom = chosen.data?.connection ? `${chosen.data.connection.display_name} · ${chosen.data.model ?? ""}` : null;
  const demo = about.data.demo_model && !custom;
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
            {custom ?? (demo ? "Demo model" : (about.data.chat_model ?? about.data.model_provider))}
          </span>
          <span className="block truncate text-xs text-stone-600">
            {custom ? "Default model" : demo ? "Offline · follows simple rules" : `via ${about.data.model_provider}`}
          </span>
        </span>
      </div>
      {about.data.dashboard_url && (
        <a
          href={about.data.dashboard_url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 flex items-center gap-2.5 rounded-xl px-2 py-1.5 text-xs text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100"
          data-testid="dashboard-link"
        >
          <span className="flex size-7 items-center justify-center">
            <Activity aria-hidden className="size-3.5" />
          </span>
          Dashboard
        </a>
      )}
    </div>
  );
}
