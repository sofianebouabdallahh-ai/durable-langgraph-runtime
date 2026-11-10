/**
 * Settings → Tools → Notifications (phase H4): where what agents send goes, and how the
 * latest ones went. Read only: the webhook is set in .env (NOTIFY_WEBHOOK_URL), and
 * each notification is sent only after you approve it in the chat.
 */
import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";

import { api, type Schemas, unwrap } from "../api/client";
import { Section } from "../ui/form";
import { Pill, Spinner } from "../ui/primitives";

type Status = Schemas["NotificationView"]["status"];

const STATUS: Record<Status, { label: string; tone: "green" | "amber" | "rose" | "stone" }> = {
  delivered: { label: "Delivered", tone: "green" },
  pending: { label: "Waiting to send", tone: "amber" },
  sending: { label: "Sending", tone: "amber" },
  failed: { label: "Not delivered", tone: "rose" },
  skipped: { label: "Not sent", tone: "stone" },
};

export function Notifications() {
  const list = useQuery({
    queryKey: ["notifications"],
    queryFn: () => unwrap(api.GET("/notifications", { params: { query: { limit: 10 } } })),
    refetchInterval: 5_000,
  });
  return (
    <Section
      title="Notifications"
      description="What agents send with Notifications, always after you approve it, goes to a webhook. Each one is sent at least once, with the same webhook-id on every retry."
      icon={<Bell aria-hidden className="size-4" />}
      testId="notifications-settings"
    >
      {!list.data ? (
        <Spinner label="Loading…" />
      ) : (
        <div className="space-y-3 text-sm">
          <p data-testid="webhook-state">
            {list.data.webhook ? (
              <>
                Sent to <code>{list.data.webhook}</code>
                {list.data.signed ? ", signed (webhook-signature)." : ", unsigned: set NOTIFY_WEBHOOK_SECRET to sign them."}
              </>
            ) : (
              <>
                No webhook is set up, so notifications are kept, not sent. Set <code>NOTIFY_WEBHOOK_URL</code> in{" "}
                <code>.env</code> and restart.
              </>
            )}
          </p>
          {list.data.notifications.length > 0 && (
            <ul className="divide-y divide-stone-200/70 dark:divide-stone-800/70" aria-label="Latest notifications">
              {list.data.notifications.map((n) => (
                <li key={n.id} className="flex items-start gap-3 py-2" data-testid="notification">
                  <div className="min-w-0 flex-1">
                    <div className="truncate">
                      To <strong>{n.to}</strong>: {n.message}
                    </div>
                    {n.last_error && n.status !== "delivered" && <div className="truncate text-xs text-stone-500">{n.last_error}</div>}
                  </div>
                  <Pill tone={STATUS[n.status].tone}>{STATUS[n.status].label}</Pill>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Section>
  );
}
