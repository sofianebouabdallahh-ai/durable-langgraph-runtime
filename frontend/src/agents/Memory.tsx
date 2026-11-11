/**
 * What an agent remembers (H8): the notes it keeps for you, in every chat with it. Yours
 * to see and remove: delete one for good, bring back one it was asked to forget, or
 * forget everything. A change shows in its very next answer.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, noContent, type Schemas, unwrap } from "../api/client";
import { href } from "../app/route";
import { problemText } from "../chat/problems";
import { Dialog } from "../ui/form";
import { Button, Spinner } from "../ui/primitives";
import { agentLabel } from "../ui/words";

type Note = Schemas["NoteView"];

export function MemorySection({ name, displayName, focus = false }: { name: string; displayName: string; focus?: boolean }) {
  const client = useQueryClient();
  const key = ["memory", name];
  const memory = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/agents/{name}/memory", { params: { path: { name } } })) });
  const [clearing, setClearing] = useState(false);
  const [deleting, setDeleting] = useState<Note | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const done = {
    onSuccess: () => { setNotice(null); setDeleting(null); void client.invalidateQueries({ queryKey: key }); },
    onError: (e: unknown) => { setNotice(problemText(e)); },
  };
  const path = (note_id: string) => ({ params: { path: { name, note_id } } });
  const remove = useMutation({ mutationFn: (id: string) => noContent(api.DELETE("/agents/{name}/memory/{note_id}", path(id))), ...done });
  const restore = useMutation({ mutationFn: (id: string) => unwrap(api.POST("/agents/{name}/memory/{note_id}/restore", path(id))), ...done });
  const clear = useMutation({
    mutationFn: () => unwrap(api.DELETE("/agents/{name}/memory", { params: { path: { name } } })),
    onSuccess: () => { setClearing(false); setNotice(null); void client.invalidateQueries({ queryKey: key }); },
    onError: (e: unknown) => { setNotice(problemText(e)); },
  });
  const ref = useRef<HTMLElement>(null);
  const scrolled = useRef(false);
  const loaded = memory.data !== undefined;
  useEffect(() => {
    // Once, when it first shows: not again after a delete or a refetch.
    if (focus && loaded && !scrolled.current) {
      scrolled.current = true;
      ref.current?.scrollIntoView({ block: "start" });
    }
  }, [focus, loaded]);

  const notes = memory.data?.notes ?? [];
  const remembered = notes.filter((n) => !n.forgotten_at);
  const forgotten = notes.filter((n) => n.forgotten_at);
  return (
    <section ref={ref} aria-labelledby="memory-title" className="mt-10 scroll-mt-6" data-testid="memory">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="memory-title" className="flex items-center gap-2 font-display text-2xl font-medium">
            <Brain aria-hidden className="size-5 text-stone-400" /> What it remembers
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-stone-500 dark:text-stone-400">
            Notes {displayName} saved when you asked it to remember something. It sees them in every chat with you, and they go to its model with
            each message. Keys, passwords and card numbers are never kept.
          </p>
        </div>
        {remembered.length + forgotten.length > 0 && (
          <Button size="sm" variant="danger" onClick={() => { setClearing(true); }}>
            <Trash2 aria-hidden className="size-3.5" /> Forget everything
          </Button>
        )}
      </div>
      {notice && <div role="alert" className="mt-3 text-sm text-rose-600">{notice}</div>}
      <div className="mt-5 rounded-2xl border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
        {memory.isPending ? (
          <Spinner className="m-5" label="Loading…" />
        ) : remembered.length === 0 ? (
          <p className="p-5 text-sm text-stone-500">
            {forgotten.length > 0
              ? `Nothing right now: ${displayName} was asked to forget everything it had.`
              : `Nothing yet. Ask ${displayName} to remember something in a chat, and it shows here.`}
          </p>
        ) : (
          <ul className="divide-y divide-stone-100 dark:divide-stone-800" aria-label="Remembered">
            {remembered.map((n) => (
              <NoteRow key={n.id} note={n}>
                <Button size="sm" variant="ghost" aria-label={`Delete “${n.text}”`} disabled={remove.isPending} onClick={() => { setDeleting(n); }}>
                  <Trash2 aria-hidden className="size-3.5" />
                </Button>
              </NoteRow>
            ))}
          </ul>
        )}
      </div>
      {forgotten.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-stone-600 dark:text-stone-400">
            Forgotten ({forgotten.length}): {displayName} was asked to forget these, and no longer sees them
          </summary>
          <ul className="mt-2 divide-y divide-stone-100 rounded-2xl border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900" aria-label="Forgotten">
            {forgotten.map((n) => (
              <NoteRow key={n.id} note={n} muted>
                <Button size="sm" variant="ghost" aria-label={`Restore “${n.text}”`} disabled={restore.isPending} onClick={() => { restore.mutate(n.id); }}>
                  <RotateCcw aria-hidden className="size-3.5" /> Restore
                </Button>
                <Button size="sm" variant="ghost" aria-label={`Delete “${n.text}” for good`} disabled={remove.isPending} onClick={() => { setDeleting(n); }}>
                  <Trash2 aria-hidden className="size-3.5" />
                </Button>
              </NoteRow>
            ))}
          </ul>
        </details>
      )}
      <Dialog open={deleting !== null} onClose={() => { setDeleting(null); }} title="Delete this note for good?">
        <p className="text-sm break-words">“{deleting?.text}”</p>
        <p className="mt-2 text-sm text-stone-600 dark:text-stone-400">{displayName} won't see it again, and it can't be brought back.</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => { setDeleting(null); }}>Cancel</Button>
          <Button variant="danger" onClick={() => { if (deleting) remove.mutate(deleting.id); }} disabled={remove.isPending}>Delete</Button>
        </div>
      </Dialog>
      <Dialog open={clearing} onClose={() => { setClearing(false); }} title={`Forget everything ${displayName} remembers?`}>
        <p className="text-sm">
          All {notes.length} notes are deleted for good, the forgotten ones too. Your chats stay as they are. This can't be undone.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => { setClearing(false); }}>Cancel</Button>
          <Button variant="danger" onClick={() => { clear.mutate(); }} disabled={clear.isPending}>Forget everything</Button>
        </div>
      </Dialog>
    </section>
  );
}

function NoteRow({ note, muted = false, children }: { note: Note; muted?: boolean; children: React.ReactNode }) {
  const when = new Date(note.saved_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  return (
    <li className="flex items-start gap-3 px-5 py-3">
      <div className="min-w-0 flex-1">
        <p className={`text-sm break-words ${muted ? "text-stone-500 line-through decoration-stone-300" : "text-stone-800 dark:text-stone-200"}`}>{note.text}</p>
        <p className="mt-0.5 text-xs text-stone-500">
          {when}
          {note.helper && <> · kept by its helper {agentLabel(note.helper)}</>}
          {note.session_id && (
            <>
              {" · "}
              <a className="underline decoration-stone-300 underline-offset-2 hover:text-stone-800 dark:hover:text-stone-200" href={href({ page: "chat", sessionId: note.session_id })}>
                the chat it came from
              </a>
            </>
          )}
        </p>
      </div>
      <div className="flex shrink-0 gap-1">{children}</div>
    </li>
  );
}
