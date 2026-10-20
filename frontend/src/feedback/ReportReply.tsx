/** "Report this reply" (L5): a zip to attach, and the issue that asks for it. */
import { useState } from "react";

import { API_BASE } from "../api/client";
import { useAbout } from "../sessions/ModelStatus";
import { Dialog } from "../ui/form";
import { Button } from "../ui/primitives";
import { replyIssueUrl } from "./report";

export function ReportReply({ runId, agent }: { runId: string; agent: string }) {
  const about = useAbout();
  const [open, setOpen] = useState(false);
  const [withText, setWithText] = useState(false);
  const zip = `${API_BASE}/runs/${encodeURIComponent(runId)}/report${withText ? "?include_chat=true" : ""}`;
  return (
    <>
      <button type="button" onClick={() => { setOpen(true); }} className="underline-offset-2 hover:underline" data-testid="report-reply">
        Report this reply
      </button>
      <Dialog open={open} onClose={() => { setOpen(false); }} title="Report this reply">
        <div className="space-y-4 text-sm" data-testid="report-dialog">
          <p className="text-stone-600 dark:text-stone-400">
            Download the report, then attach it to the issue. Nothing is uploaded from here.
          </p>
          <ul className="list-disc space-y-1 pl-5 text-stone-700 dark:text-stone-300">
            <li>what happened, step by step (no text: names of steps and tools, times, outcomes)</li>
            <li>the agent&apos;s definition, if it&apos;s one you made</li>
            <li>Nuria&apos;s version</li>
          </ul>
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={withText} onChange={(e) => { setWithText(e.target.checked); }} className="mt-1" />
            <span>Also include this conversation&apos;s text (what you wrote and what it answered)</span>
          </label>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => { setOpen(false); }}>Close</Button>
            <a href={zip} download className="inline-flex h-10 items-center rounded-xl border border-stone-200 px-4 font-medium shadow-soft hover:bg-stone-50 dark:border-stone-700 dark:hover:bg-stone-800" data-testid="report-download">
              Download the report
            </a>
            <a href={replyIssueUrl(runId, about.data?.version ?? null, agent)} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center rounded-xl bg-stone-900 px-4 font-medium text-white shadow-soft hover:bg-stone-800 dark:bg-stone-100 dark:text-stone-900" data-testid="report-github">
              Open a GitHub issue
            </a>
          </div>
        </div>
      </Dialog>
    </>
  );
}
