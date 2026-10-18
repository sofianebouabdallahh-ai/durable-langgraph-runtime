/** Home: greet, pick an agent, write the first message; the chat starts from it. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Calculator, NotebookPen, Users } from "lucide-react";
import { useState } from "react";

import { api, unwrap } from "../api/client";
import { sendMessage } from "../api/send";
import { type Route } from "../app/route";
import { Mark } from "../ui/Logo";
import { agentLabel } from "../ui/words";
import { Composer } from "./Composer";
import { problemText, titleFrom } from "./problems";

const SUGGESTIONS = [
  { icon: Calculator, title: "Calculate", text: "What is 12 * (3 + 4)?" },
  { icon: Users, title: "Research with two helpers", text: "Research Redis Streams and compute 12 * 4" },
  { icon: NotebookPen, title: "Remember something", text: "Remember that the demo is on Friday" },
  { icon: Bell, title: "Ask before acting", text: "Notify the team that the build is green" },
];

function greeting(now = new Date()): string {
  const h = now.getHours();
  return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export function Home({ go }: { go: (route: Route) => void }) {
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => unwrap(api.GET("/agents")) });
  const [agent, setAgent] = useState("chat");
  const [notice, setNotice] = useState<string | null>(null);
  const choices = (agents.data ?? []).filter((a) => !a.hidden);
  const chosen = choices.find((a) => a.name === agent)?.display_name ?? agentLabel(agent);

  const start = async (text: string): Promise<boolean> => {
    setNotice(null);
    try {
      const session = await unwrap(api.POST("/sessions", { body: { agent, title: titleFrom(text) } }));
      await sendMessage(session.id, text);
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
      go({ page: "chat", sessionId: session.id });
      return true;
    } catch (e) {
      setNotice(problemText(e));
      return false;
    }
  };

  return (
    <div className="glow flex min-h-full flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-2xl">
        <div className="mb-8 flex flex-col items-center text-center">
          <Mark size={52} className="mb-5 drop-shadow-sm" />
          <h1 className="font-display text-4xl font-medium tracking-tight sm:text-5xl">{greeting()}</h1>
          <p className="mt-3 text-lg text-stone-500 dark:text-stone-400">What can {chosen} do for you today?</p>
        </div>
        {notice && (
          <div role="alert" className="mb-3 rounded-xl bg-rose-50 px-4 py-2.5 text-sm text-rose-800 ring-1 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900">
            {notice}
          </div>
        )}
        <Composer
          busy={false}
          autoFocus
          onSend={start}
          placeholder={`Message ${chosen}…`}
          leading={
            choices.length > 1 && (
              <label className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800">
                <span>Agent</span>
                <select
                  value={agent}
                  onChange={(e) => {
                    setAgent(e.target.value);
                  }}
                  aria-label="Agent"
                  className="cursor-pointer bg-transparent font-medium text-stone-800 focus:outline-none dark:text-stone-200"
                >
                  {choices.map((a) => (
                    <option key={a.name} value={a.name}>
                      {a.display_name}
                    </option>
                  ))}
                </select>
              </label>
            )
          }
        />
        <div className="mt-6 grid gap-2.5 sm:grid-cols-2">
          {SUGGESTIONS.map(({ icon: Icon, title, text }) => (
            <button
              key={title}
              type="button"
              onClick={() => void start(text)}
              className="group flex items-start gap-3 rounded-2xl border border-stone-200 bg-white/70 p-3.5 text-left shadow-soft backdrop-blur transition hover:-translate-y-0.5 hover:border-stone-300 hover:bg-white focus-visible:outline-2 focus-visible:outline-sun-500 dark:border-stone-800 dark:bg-stone-900/60 dark:hover:border-stone-700 dark:hover:bg-stone-900"
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-sun-50 text-sun-600 ring-1 ring-sun-100 transition group-hover:bg-sun-100 dark:bg-sun-700/15 dark:text-sun-300 dark:ring-sun-700/30">
                <Icon aria-hidden className="size-4" />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium">{title}</span>
                <span className="block truncate text-[13px] text-stone-500 dark:text-stone-400">{text}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
