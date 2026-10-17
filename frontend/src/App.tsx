import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api/client";
import { ChatView } from "./chat/ChatView";
import { useSessionRoute } from "./sessions/route";
import { Sidebar } from "./sessions/Sidebar";
import { Badge } from "./ui/primitives";

export function App() {
  const [sessionId, open] = useSessionRoute();
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
          <span className="font-medium md:hidden">Agent Runtime</span>
          <span className="ml-auto flex items-center gap-2">
            {about.data?.demo_model && (
              <span title="The offline demo model follows simple rules. Connect a real model with ./setup.sh --model …">
                <Badge tone="amber">Demo model</Badge>
              </span>
            )}
            {about.data && !about.data.demo_model && <Badge>{about.data.chat_model ?? about.data.model_provider}</Badge>}
          </span>
        </header>
        <div className="min-h-0 flex-1">
          {sessionId ? (
            <ChatView key={sessionId} sessionId={sessionId} />
          ) : (
            <Welcome onOpen={open} />
          )}
        </div>
      </main>
    </div>
  );
}

function Welcome({ onOpen }: { onOpen: (id: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-2xl font-semibold">Chat with your agents</h1>
      <p className="max-w-md text-slate-600 dark:text-slate-400">
        Every reply survives crashes and restarts: try stopping a worker in the middle of an answer.
      </p>
      <div className="w-full max-w-xs md:hidden">
        <Sidebar current={null} onOpen={onOpen} />
      </div>
      <p className="hidden text-sm text-slate-500 md:block">Start with “New chat” on the left.</p>
    </div>
  );
}
