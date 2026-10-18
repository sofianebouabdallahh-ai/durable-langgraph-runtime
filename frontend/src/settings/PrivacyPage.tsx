/** Settings → Privacy (L5): the opt-in usage counts, shown exactly as they'd be shared. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "../api/client";
import { Switch } from "../ui/form";
import { Spinner } from "../ui/primitives";

export function PrivacyPage() {
  const client = useQueryClient();
  const telemetry = useQuery({ queryKey: ["telemetry"], queryFn: () => unwrap(api.GET("/telemetry")) });
  const toggle = useMutation({
    mutationFn: (sharing: boolean) => unwrap(api.PUT("/telemetry", { body: { sharing } })),
    onSuccess: (data) => { client.setQueryData(["telemetry"], data); },
  });
  if (!telemetry.data) return <Spinner label="Loading…" />;
  const t = telemetry.data;
  return (
    <div className="mx-auto max-w-2xl space-y-6 px-6 py-8">
      <div>
        <h1 className="font-display text-2xl font-medium">Privacy</h1>
        <p className="mt-2 text-sm text-stone-600 dark:text-stone-400">
          Everything stays on this computer: your chats, agents, skills and keys. Nuria sends nothing anywhere by itself.
        </p>
      </div>
      <div className="rounded-2xl border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-900">
        <Switch
          checked={t.sharing}
          disabled={toggle.isPending}
          onChange={(on) => { toggle.mutate(on); }}
          label="Share anonymous usage counts with my feedback"
          description="When on, these counts can be added to a feedback report you send. Never a message, a name, a key or a link. Off unless you turn it on."
        />
        <table className="mt-5 w-full text-left text-sm" data-testid="usage-table">
          <thead className="text-xs text-stone-500">
            <tr><th className="py-1 font-medium">What</th><th className="py-1 font-medium">Right now</th></tr>
          </thead>
          <tbody>
            {Object.entries(t.fields).map(([key, what]) => (
              <tr key={key} className="border-t border-stone-100 dark:border-stone-800">
                <td className="py-1.5 pr-4 text-stone-700 dark:text-stone-300">{what}</td>
                <td className="py-1.5 font-mono text-xs">{JSON.stringify(t.report[key] ?? null)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
