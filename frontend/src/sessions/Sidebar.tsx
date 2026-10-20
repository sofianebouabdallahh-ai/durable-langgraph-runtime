/** The sidebar: Nuria, navigation, and the chats by recency. */
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Bot, Boxes, MessageSquare, MessageSquareHeart, Plus, Search, Shield } from "lucide-react";
import { useMemo, useState } from "react";

import { api, unwrap, type SessionView } from "../api/client";
import { href, type Route } from "../app/route";
import { Logo } from "../ui/Logo";
import { FeedbackDialog } from "../feedback/FeedbackDialog";
import { ModelStatus } from "./ModelStatus";

const DAY = 86_400_000;

function groupOf(iso: string, now: number): string {
  const t = Date.parse(iso);
  const today = new Date(now).setHours(0, 0, 0, 0);
  if (t >= today) return "Today";
  if (t >= today - DAY) return "Yesterday";
  if (t >= today - 7 * DAY) return "Previous 7 days";
  return "Older";
}

export function Sidebar({ route, onNavigate }: { route: Route; onNavigate: () => void }) {
  const [query, setQuery] = useState("");
  const [feedback, setFeedback] = useState(false);
  const [now] = useState(() => Date.now()); // "Today", "Yesterday": relative to when the page opened
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: () => unwrap(api.GET("/sessions", { params: { query: { status: "active", limit: 100 } } })),
  });
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = new Map<string, SessionView[]>();
    for (const s of sessions.data ?? []) {
      if (q && !(s.title ?? "new chat").toLowerCase().includes(q)) continue;
      const g = groupOf(s.last_activity_at, now);
      out.set(g, [...(out.get(g) ?? []), s]);
    }
    return [...out.entries()];
  }, [sessions.data, query, now]);
  const current = route.page === "chat" ? route.sessionId : null;

  return (
    <nav aria-label="Main" className="flex h-full flex-col">
      <div className="flex items-center justify-between px-4 pt-4 pb-3">
        <a href={href({ page: "home" })} onClick={onNavigate} className="rounded-lg focus-visible:outline-2 focus-visible:outline-sun-500">
          <Logo />
        </a>
      </div>
      <div className="space-y-1 px-3">
        <a
          href={href({ page: "home" })}
          onClick={onNavigate}
          className="flex h-10 items-center gap-2 rounded-xl bg-stone-900 px-3 text-sm font-medium text-white shadow-soft transition hover:bg-stone-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sun-500 dark:bg-stone-100 dark:text-stone-900 dark:hover:bg-white"
        >
          <Plus aria-hidden className="size-4" /> New chat
        </a>
        <NavLink to={{ page: "agents" }} active={route.page === "agents" || route.page === "agent" || route.page === "studio"} onNavigate={onNavigate} icon={<Bot aria-hidden className="size-4" />}>
          Agents
        </NavLink>
        <NavLink to={{ page: "skills" }} active={route.page === "skills"} onNavigate={onNavigate} icon={<BookOpen aria-hidden className="size-4" />}>
          Skills
        </NavLink>
        <NavLink to={{ page: "models" }} active={route.page === "models"} onNavigate={onNavigate} icon={<Boxes aria-hidden className="size-4" />}>
          Models
        </NavLink>
      </div>

      <div className="mt-5 px-3">
        <label className="relative block">
          <span className="sr-only">Search chats</span>
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-stone-600" />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
            }}
            placeholder="Search chats"
            className="h-9 w-full rounded-xl border border-stone-200 bg-white pr-3 pl-9 text-sm placeholder:text-stone-400 focus:border-sun-400 focus:ring-2 focus:ring-sun-200 focus:outline-none dark:border-stone-800 dark:bg-stone-900 dark:focus:ring-sun-700/30"
          />
        </label>
      </div>

      <div className="scrollbar-thin mt-3 min-h-0 flex-1 overflow-y-auto px-3 pb-3" data-testid="session-list">
        {groups.map(([group, items]) => (
          <section key={group} className="mt-3 first:mt-0">
            <h2 className="px-3 pb-1 text-[11px] font-semibold tracking-wider text-stone-600 uppercase">{group}</h2>
            <ul className="space-y-0.5">
              {items.map((s) => (
                <li key={s.id}>
                  <a
                    href={href({ page: "chat", sessionId: s.id })}
                    onClick={onNavigate}
                    aria-current={s.id === current ? "page" : undefined}
                    className={`group flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition focus-visible:outline-2 focus-visible:outline-sun-500 ${
                      s.id === current
                        ? "bg-white font-medium text-stone-900 shadow-soft ring-1 ring-stone-200 dark:bg-stone-800 dark:text-white dark:ring-stone-700"
                        : "text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800/60 dark:hover:text-stone-100"
                    }`}
                  >
                    <MessageSquare aria-hidden className="size-3.5 shrink-0 text-stone-600" />
                    <span className="truncate">{s.title ?? "New chat"}</span>
                    {s.active_run_id && (
                      <span className="ml-auto size-1.5 shrink-0 animate-pulse rounded-full bg-sun-500" title="Answering…" />
                    )}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {sessions.data?.length === 0 && (
          <p className="px-3 py-6 text-center text-sm text-stone-600">Your chats will appear here.</p>
        )}
      </div>
      <div className="flex items-center gap-1 border-t border-stone-200 px-3 pt-2 dark:border-stone-800">
        <button
          type="button"
          onClick={() => { setFeedback(true); }}
          className="flex h-8 flex-1 items-center gap-2 rounded-lg px-2 text-xs text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100"
          data-testid="send-feedback"
        >
          <MessageSquareHeart aria-hidden className="size-3.5" /> Send feedback
        </button>
        <a
          href={href({ page: "privacy" })}
          onClick={onNavigate}
          aria-current={route.page === "privacy" ? "page" : undefined}
          className="flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100"
        >
          <Shield aria-hidden className="size-3.5" /> Privacy
        </a>
      </div>
      <FeedbackDialog open={feedback} onClose={() => { setFeedback(false); }} />
      <ModelStatus />
    </nav>
  );
}

function NavLink({
  to,
  active,
  icon,
  children,
  onNavigate,
}: {
  to: Route;
  active: boolean;
  icon: React.ReactNode;
  children: React.ReactNode;
  onNavigate: () => void;
}) {
  return (
    <a
      href={href(to)}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`flex h-9 items-center gap-2 rounded-xl px-3 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-sun-500 ${
        active
          ? "bg-stone-200/70 text-stone-900 dark:bg-stone-800 dark:text-white"
          : "text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800/60 dark:hover:text-stone-100"
      }`}
    >
      {icon}
      {children}
    </a>
  );
}
