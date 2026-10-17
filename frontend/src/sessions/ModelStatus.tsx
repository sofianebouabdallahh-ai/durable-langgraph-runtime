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
      <div className="flex items-start gap-3 rounded-xl p-2" data-testid="model-status">
        <span className={`mt-0.5 flex size-8 items-center justify-center rounded-lg ${demo ? "bg-sun-100 text-sun-700 dark:bg-sun-700/20 dark:text-sun-300" : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"}`}>
          {demo ? <Sparkles aria-hidden className="size-4" /> : <Cpu aria-hidden className="size-4" />}
        </span>
        <span className="min-w-0 text-xs leading-relaxed">
          <span className="block text-sm font-medium text-stone-800 dark:text-stone-200">
            {demo ? "Demo model" : (about.data.chat_model ?? about.data.model_provider)}
          </span>
          <span className="block text-stone-500">
            {demo ? (
              <>
                Offline, follows simple rules. Connect a real one: <code className="font-mono text-[11px]">./setup.sh --model ollama</code>
              </>
            ) : (
              `via ${about.data.model_provider}`
            )}
          </span>
        </span>
      </div>
    </div>
  );
}
