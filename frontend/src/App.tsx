import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "./api/client";
import { ChatView } from "./chat/ChatView";
import { useSessionRoute } from "./sessions/route";
import { Sidebar } from "./sessions/Sidebar";
import { Badge } from "./ui/primitives";

export function App() {
  const [sessionId, go] = useSessionRoute();
  const [menu, setMenu] = useState(false); // the chats list on a small screen
  const open = (id: string | null) => {
    setMenu(false);
    go(id);
  };
  const about = useQuery({ queryKey: ["about"], queryFn: () => unwrap(api.GET("/about")), staleTime: Infinity });
  return (
    <div className="flex h-full bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white md:block dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-2 px-4 pt-4 font-semibold">
          <img src="/favicon.svg" alt="" className="size-6" /> Agent Runtime
        </div>
        <Sidebar current={sessionId} onOpen={open} />
      </aside>
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-slate-200 bg-white px-4 py-2 dark:border-slate-800 dark:bg-slate-900">
          <button
            type="button"
            className="rounded-md px-2 py-1 text-sm font-medium text-slate-700 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-indigo-500 md:hidden dark:text-slate-200 dark:hover:bg-slate-800"
            aria-expanded={menu}
            aria-controls="mobile-chats"
            onClick={() => {
              setMenu(!menu);
            }}
          >
            ☰ Chats
          </button>
          <span className="ml-auto flex items-center gap-2">
            {about.data?.demo_model && (
              <span title="The offline demo model follows simple rules. Connect a real model with ./setup.sh --model …">
                <Badge tone="amber">Demo model</Badge>
              </span>
            )}
            {about.data && !about.data.demo_model && <Badge>{about.data.chat_model ?? about.data.model_provider}</Badge>}
          </span>
        </header>
        {menu && (
          <div id="mobile-chats" className="border-b border-slate-200 bg-white md:hidden dark:border-slate-800 dark:bg-slate-900">
            <div className="h-[60vh]">
              <Sidebar current={sessionId} onOpen={open} />
            </div>
          </div>
        )}
        <div className="min-h-0 flex-1">
          {sessionId ? (
            <ChatView key={sessionId} sessionId={sessionId} />
          ) : (
            <Welcome />
          )}
        </div>
      </main>
    </div>
  );
}

function Welcome() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-2xl font-semibold">Chat with your agents</h1>
      <p className="max-w-md text-slate-600 dark:text-slate-400">
        Every reply survives crashes and restarts: try stopping a worker in the middle of an answer.
      </p>
      <p className="text-sm text-slate-500">
        <span className="hidden md:inline">Start with “New chat” on the left.</span>
        <span className="md:hidden">Open “☰ Chats” to start one.</span>
      </p>
    </div>
  );
}
