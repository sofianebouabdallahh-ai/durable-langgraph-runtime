import { Menu, X } from "lucide-react";
import { lazy, Suspense, useState } from "react";

import { useRoute } from "./app/route";
import { ChatView } from "./chat/ChatView";
import { Home } from "./chat/Home";
import { Sidebar } from "./sessions/Sidebar";
import { Spinner } from "./ui/primitives";

// The Agents pages and the Studio load when first opened: most visits are chats.
const AgentsPage = lazy(() => import("./agents/AgentsPage").then((m) => ({ default: m.AgentsPage })));
const AgentDetail = lazy(() => import("./agents/AgentsPage").then((m) => ({ default: m.AgentDetail })));
const StudioEditor = lazy(() => import("./studio/StudioEditor").then((m) => ({ default: m.StudioEditor })));
import { Logo } from "./ui/Logo";

export function App() {
  const [route, go] = useRoute();
  const [drawer, setDrawer] = useState(false); // the sidebar on a small screen
  const close = () => {
    setDrawer(false);
  };

  return (
    <div className="flex h-full">
      <aside className="hidden w-72 shrink-0 border-r border-stone-200 bg-stone-100/60 md:block dark:border-stone-800 dark:bg-stone-900/40">
        <Sidebar route={route} onNavigate={close} />
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button type="button" aria-label="Close the menu" className="absolute inset-0 bg-stone-950/30 backdrop-blur-sm" onClick={close} />
          <div id="mobile-menu" className="absolute inset-y-0 left-0 w-80 max-w-[85%] bg-stone-50 shadow-lift dark:bg-stone-950">
            <button type="button" aria-label="Close the menu" onClick={close} className="absolute top-4 right-3 rounded-lg p-1.5 text-stone-500 hover:bg-stone-200 dark:hover:bg-stone-800">
              <X aria-hidden className="size-5" />
            </button>
            <Sidebar route={route} onNavigate={close} />
          </div>
        </div>
      )}

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-stone-200 px-3 md:hidden dark:border-stone-800">
          <button
            type="button"
            aria-label="Open the menu"
            aria-expanded={drawer}
            aria-controls="mobile-menu"
            onClick={() => {
              setDrawer(true);
            }}
            className="rounded-lg p-2 text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800"
          >
            <Menu aria-hidden className="size-5" />
          </button>
          <Logo />
        </div>
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
          {route.page === "chat" && <ChatView key={route.sessionId} sessionId={route.sessionId} />}
          {route.page === "home" && <Home go={go} />}
          <Suspense fallback={<Spinner className="m-10" label="Loading…" />}>
            {route.page === "agents" && <AgentsPage go={go} />}
            {route.page === "studio" && <StudioEditor key={route.agentId} agentId={route.agentId} go={go} />}
            {route.page === "agent" && <AgentDetail key={route.name} name={route.name} go={go} />}
          </Suspense>
        </div>
      </main>
    </div>
  );
}
