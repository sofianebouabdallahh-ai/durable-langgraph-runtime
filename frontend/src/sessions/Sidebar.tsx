/** The sessions sidebar: newest activity first, a new chat with any agent. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "../api/client";
import { Button } from "../ui/primitives";

export function Sidebar({ current, onOpen }: { current: string | null; onOpen: (id: string) => void }) {
  const queryClient = useQueryClient();
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: () => unwrap(api.GET("/sessions", { params: { query: { status: "active", limit: 50 } } })),
  });
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => unwrap(api.GET("/agents")) });
  const [agent, setAgent] = useState("chat");
  const create = useMutation({
    mutationFn: (name: string) => unwrap(api.POST("/sessions", { body: { agent: name } })),
    onSuccess: (s) => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
      onOpen(s.id);
    },
  });
  const chatAgents = (agents.data ?? []).filter((a) => a.name !== "example");

  return (
    <nav aria-label="Chats" className="flex h-full flex-col gap-3 p-3">
      <div className="flex gap-2">
        <Button variant="primary" className="flex-1" disabled={create.isPending} onClick={() => {
            create.mutate(agent);
          }}>
          + New chat
        </Button>
      </div>
      {chatAgents.length > 1 && (
        <label className="text-xs text-slate-500">
          Assistant
          <select
            value={agent}
            onChange={(e) => {
              setAgent(e.target.value);
            }}
            className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          >
            {chatAgents.map((a) => (
              <option key={a.name} value={a.name}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {create.isError && <div role="alert" className="text-sm text-rose-600">Couldn't start a chat.</div>}
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto" data-testid="session-list">
        {sessions.data?.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => {
                onOpen(s.id);
              }}
              aria-current={s.id === current ? "page" : undefined}
              className={`w-full truncate rounded-lg px-3 py-2 text-left text-sm focus-visible:outline-2 focus-visible:outline-indigo-500 ${
                s.id === current
                  ? "bg-indigo-50 font-medium text-indigo-900 dark:bg-indigo-950 dark:text-indigo-100"
                  : "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
              }`}
            >
              {s.title ?? "New chat"}
              {s.active_run_id && <span className="ml-1 text-xs text-amber-600">●</span>}
            </button>
          </li>
        ))}
        {sessions.data?.length === 0 && <li className="px-3 py-2 text-sm text-slate-500">No chats yet.</li>}
      </ul>
    </nav>
  );
}
