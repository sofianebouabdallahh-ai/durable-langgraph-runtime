/** Where you write: grows with the text; Enter sends, Shift+Enter breaks the line. */
import { ArrowUp, Square } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

export function Composer({
  busy,
  waitingApproval = false,
  onSend,
  onStop,
  placeholder = "Message Nuria…",
  leading,
  autoFocus = false,
}: {
  busy: boolean;
  waitingApproval?: boolean;
  onSend: (text: string) => Promise<boolean>;
  onStop?: () => Promise<void>;
  placeholder?: string;
  leading?: ReactNode;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${String(Math.min(el.scrollHeight, 220))}px`;
  }, [text]);

  const submit = async () => {
    const value = text.trim();
    if (!value || busy || sending) return;
    setSending(true);
    if (await onSend(value)) setText("");
    setSending(false);
  };

  return (
    <form
      className="rounded-2xl border border-stone-200 bg-white shadow-lift transition focus-within:border-stone-300 focus-within:ring-4 focus-within:ring-sun-100 dark:border-stone-700 dark:bg-stone-900 dark:focus-within:ring-sun-700/20"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label className="block">
        <span className="sr-only">Message</span>
        <textarea
          ref={box}
          value={text}
          autoFocus={autoFocus}
          onChange={(e) => {
            setText(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={1}
          maxLength={32000}
          placeholder={waitingApproval ? "Approve or reject above to continue…" : placeholder}
          className="block max-h-56 w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[15px] leading-relaxed placeholder:text-stone-400 focus:outline-none"
        />
      </label>
      <div className="flex items-center gap-2 px-2.5 pb-2.5">
        <div className="min-w-0 flex-1">{leading}</div>
        {busy && onStop ? (
          <button
            type="button"
            onClick={() => void onStop()}
            aria-label="Stop the reply"
            className="flex size-9 items-center justify-center rounded-full border border-stone-300 bg-white text-stone-800 transition hover:bg-stone-100 focus-visible:outline-2 focus-visible:outline-sun-500 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100 dark:hover:bg-stone-700"
          >
            <Square aria-hidden className="size-3.5 fill-current" />
          </button>
        ) : (
          <button
            type="submit"
            aria-label="Send"
            disabled={!text.trim() || sending || busy}
            className="flex size-9 items-center justify-center rounded-full bg-stone-900 text-white transition hover:bg-stone-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sun-500 disabled:bg-stone-200 disabled:text-stone-400 dark:bg-stone-100 dark:text-stone-900 dark:disabled:bg-stone-800 dark:disabled:text-stone-600"
          >
            <ArrowUp aria-hidden className="size-4" strokeWidth={2.5} />
          </button>
        )}
      </div>
    </form>
  );
}
