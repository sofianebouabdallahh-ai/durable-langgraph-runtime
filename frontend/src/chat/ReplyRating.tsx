/**
 * 👍 / 👎 under a reply (phase L7d). Stored with the turn's agent and version, shown per
 * agent in Activity. Click the chosen one again to take it back; 👎 asks (optionally) what
 * was wrong.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { api, unwrap } from "../api/client";

type Rating = "up" | "down";

const button =
  "inline-flex items-center rounded-lg p-1.5 text-stone-500 transition hover:bg-stone-100 hover:text-stone-700 focus-visible:outline-2 focus-visible:outline-sun-500 aria-pressed:text-stone-900 dark:hover:bg-stone-800 dark:hover:text-stone-200 dark:aria-pressed:text-stone-100";

export function ReplyRating({ runId }: { runId: string }) {
  const client = useQueryClient();
  const key = ["feedback", runId];
  const current = useQuery({
    queryKey: key,
    queryFn: () => unwrap(api.GET("/runs/{run_id}/feedback", { params: { path: { run_id: runId } } })),
    staleTime: Infinity,
  });
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: async (next: { rating: Rating | null; reason?: string }) => {
      const path = { params: { path: { run_id: runId } } };
      if (next.rating === null) {
        await api.DELETE("/runs/{run_id}/feedback", path);
        return null;
      }
      return unwrap(api.PUT("/runs/{run_id}/feedback", { ...path, body: { rating: next.rating, reason: next.reason ?? null } }));
    },
    onSuccess: (saved) => {
      client.setQueryData(key, saved);
      void client.invalidateQueries({ queryKey: ["activity"] });
    },
  });
  const rating = current.data?.rating ?? null;

  const choose = (r: Rating) => {
    const next = rating === r ? null : r;
    setAsking(next === "down");
    setReason("");
    save.mutate({ rating: next });
  };

  return (
    <span className="inline-flex items-center gap-0.5" data-testid="reply-rating">
      <button type="button" className={button} aria-label="Good reply" aria-pressed={rating === "up"} onClick={() => { choose("up"); }}>
        <ThumbsUp aria-hidden className="size-3.5" fill={rating === "up" ? "currentColor" : "none"} />
      </button>
      <button type="button" className={button} aria-label="Bad reply" aria-pressed={rating === "down"} onClick={() => { choose("down"); }}>
        <ThumbsDown aria-hidden className="size-3.5" fill={rating === "down" ? "currentColor" : "none"} />
      </button>
      {asking && rating === "down" && (
        <form
          className="ml-1 inline-flex items-center gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({ rating: "down", reason });
            setAsking(false);
          }}
        >
          <input
            value={reason}
            onChange={(e) => { setReason(e.target.value); }}
            maxLength={500}
            placeholder="What was wrong? (optional)"
            aria-label="What was wrong? (optional)"
            className="h-7 w-56 rounded-lg border border-stone-200 bg-white px-2 text-xs dark:border-stone-700 dark:bg-stone-950"
          />
          <button type="submit" className="rounded-lg px-2 py-1 text-xs font-medium text-stone-700 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800">
            Send
          </button>
        </form>
      )}
      {current.data?.reason && !asking && <span className="ml-1 max-w-56 truncate text-xs text-stone-500" title={current.data.reason}>“{current.data.reason}”</span>}
    </span>
  );
}
