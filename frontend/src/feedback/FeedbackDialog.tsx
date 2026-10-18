/** "Send feedback" (L5, §4.8): a short form; the exact text is shown before it leaves. */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "../api/client";
import { useAbout } from "../sessions/ModelStatus";
import { Dialog, TextArea } from "../ui/form";
import { Button } from "../ui/primitives";
import { browserName, details, FEELINGS, feedbackIssueUrl, feedbackMarkdown, type Feedback } from "./report";

export function download(name: string, text: string, type = "text/markdown") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function FeedbackDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const about = useAbout();
  const usage = useQuery({ queryKey: ["telemetry"], queryFn: () => unwrap(api.GET("/telemetry")), enabled: open });
  const [form, setForm] = useState<Feedback>({ doing: "", happened: "", feeling: null });
  const [withInstall, setWithInstall] = useState(true);
  const [withUsage, setWithUsage] = useState(true);
  const sharing = usage.data?.sharing === true;
  const text = details(
    withInstall && about.data ? { version: about.data.version ?? null, model_provider: about.data.model_provider, browser: browserName(navigator.userAgent) } : null,
    sharing && withUsage && usage.data ? usage.data.report : null,
  );
  const empty = !form.doing.trim() && !form.happened.trim();
  return (
    <Dialog open={open} onClose={onClose} title="Send feedback">
      <div className="space-y-4" data-testid="feedback-dialog">
        <p className="text-sm text-stone-600 dark:text-stone-400">Thank you. Nothing is sent from here: you review it on GitHub, or download it to email.</p>
        <TextArea label="What were you doing?" rows={2} value={form.doing} onChange={(e) => { setForm({ ...form, doing: e.target.value }); }} />
        <TextArea label="What happened?" rows={3} value={form.happened} onChange={(e) => { setForm({ ...form, happened: e.target.value }); }} />
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium text-stone-800 dark:text-stone-200">How did it feel?</legend>
          <div className="flex flex-wrap gap-1.5">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                type="button"
                aria-pressed={form.feeling === n}
                onClick={() => { setForm({ ...form, feeling: form.feeling === n ? null : n }); }}
                className={`rounded-full px-3 py-1 text-sm ring-1 transition ${form.feeling === n ? "bg-stone-900 text-white ring-stone-900 dark:bg-sun-500/20 dark:text-sun-200 dark:ring-sun-500" : "ring-stone-200 hover:bg-stone-100 dark:ring-stone-700 dark:hover:bg-stone-800"}`}
              >
                {FEELINGS[n]}
              </button>
            ))}
          </div>
        </fieldset>
        <div className="space-y-1.5 text-sm">
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={withInstall} onChange={(e) => { setWithInstall(e.target.checked); }} className="mt-1" />
            <span>Include this installation&apos;s details (version, model type, browser)</span>
          </label>
          {sharing && (
            <label className="flex items-start gap-2">
              <input type="checkbox" checked={withUsage} onChange={(e) => { setWithUsage(e.target.checked); }} className="mt-1" />
              <span>Include the anonymous usage counts (Settings → Privacy)</span>
            </label>
          )}
        </div>
        {text && (
          <div>
            <div className="mb-1 text-xs font-medium text-stone-500">Also included, exactly:</div>
            <pre data-testid="feedback-details" className="max-h-32 overflow-auto rounded-lg bg-stone-100 p-2 text-xs whitespace-pre-wrap dark:bg-stone-800">{text}</pre>
          </div>
        )}
        <div className="flex flex-wrap justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>Close</Button>
          <Button disabled={empty} onClick={() => { download("nuria-feedback.md", feedbackMarkdown(form, text)); }}>Download</Button>
          <a
            href={empty ? undefined : feedbackIssueUrl(form, text)}
            target="_blank"
            rel="noreferrer"
            aria-disabled={empty}
            data-testid="feedback-github"
            className={`inline-flex h-10 items-center rounded-xl px-4 text-sm font-medium shadow-soft ${empty ? "pointer-events-none bg-stone-300 text-white dark:bg-stone-700" : "bg-stone-900 text-white hover:bg-stone-800 dark:bg-stone-100 dark:text-stone-900"}`}
          >
            Open a GitHub issue
          </a>
        </div>
      </div>
    </Dialog>
  );
}
