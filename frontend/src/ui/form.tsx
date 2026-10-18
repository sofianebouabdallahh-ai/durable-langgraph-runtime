/** Form building blocks for the Studio: one look, accessible labels, issues in place. */
import { AlertCircle } from "lucide-react";
import { type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes, useEffect, useId, useRef } from "react";

export function Section({
  title,
  description,
  icon,
  children,
  aside,
  testId,
}: {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  children: ReactNode;
  aside?: ReactNode;
  testId?: string;
}) {
  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-soft dark:border-stone-800 dark:bg-stone-900" data-testid={testId}>
      <div className="mb-4 flex items-start gap-3">
        {icon && (
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300">
            {icon}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-lg font-medium">{title}</h2>
          {description && <p className="mt-0.5 text-sm text-stone-500 dark:text-stone-400">{description}</p>}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Issues({ issues, id }: { issues: readonly { message: string }[]; id?: string }) {
  if (issues.length === 0) return null;
  return (
    <ul id={id} className="mt-1.5 space-y-0.5" data-testid="field-issues">
      {issues.map((i) => (
        <li key={i.message} className="flex items-start gap-1.5 text-[13px] text-rose-700 dark:text-rose-400">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {i.message}
        </li>
      ))}
    </ul>
  );
}

const control =
  "w-full rounded-xl border bg-white px-3 py-2 text-[15px] transition placeholder:text-stone-400 focus:ring-4 focus:outline-none dark:bg-stone-950";
const ok = "border-stone-200 focus:border-sun-400 focus:ring-sun-100 dark:border-stone-700 dark:focus:ring-sun-700/20";
const bad = "border-rose-300 focus:border-rose-400 focus:ring-rose-100 dark:border-rose-800 dark:focus:ring-rose-900/30";

export function TextField({
  label,
  hint,
  issues = [],
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode; issues?: readonly { message: string }[] }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-stone-800 dark:text-stone-200">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={issues.length > 0}
        aria-describedby={issues.length ? `${id}-issues` : undefined}
        className={`${control} ${issues.length ? bad : ok}`}
        {...props}
      />
      {hint && <div className="mt-1 text-xs text-stone-500">{hint}</div>}
      <Issues issues={issues} id={`${id}-issues`} />
    </div>
  );
}

export function TextArea({
  label,
  hint,
  issues = [],
  className = "",
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: ReactNode; issues?: readonly { message: string }[] }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-stone-800 dark:text-stone-200">
        {label}
      </label>
      <textarea
        id={id}
        aria-invalid={issues.length > 0}
        aria-describedby={issues.length ? `${id}-issues` : undefined}
        className={`${control} ${issues.length ? bad : ok} leading-relaxed ${className}`}
        {...props}
      />
      {hint && <div className="mt-1 text-xs text-stone-500">{hint}</div>}
      <Issues issues={issues} id={`${id}-issues`} />
    </div>
  );
}

/** An on/off switch with its label (role="switch"). */
export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled = false,
  hideLabel = false,
}: {
  checked: boolean;
  onChange: (on: boolean) => void;
  label: string;
  description?: ReactNode;
  disabled?: boolean;
  hideLabel?: boolean; // the label is visible elsewhere (a card's title): screen readers only
}) {
  const id = useId();
  return (
    <div className="flex items-start gap-3">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => {
          onChange(!checked);
        }}
        className={`relative mt-0.5 inline-flex h-6 w-10 shrink-0 items-center rounded-full transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sun-500 disabled:opacity-50 ${checked ? "bg-stone-900 dark:bg-sun-500" : "bg-stone-300 dark:bg-stone-700"}`}
      >
        <span className={`inline-block size-5 rounded-full bg-white shadow transition ${checked ? "translate-x-[18px]" : "translate-x-0.5"}`} />
      </button>
      <label htmlFor={id} className={hideLabel ? "sr-only" : "min-w-0 cursor-pointer text-sm"}>
        <span className="block font-medium text-stone-800 dark:text-stone-200">{label}</span>
        {description && <span className="block text-stone-500 dark:text-stone-400">{description}</span>}
      </label>
    </div>
  );
}

/** A choice of a few options, as one row of buttons (radiogroup). */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: readonly { value: T; label: string; hint?: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  const columns = options.length === 3 ? "sm:grid-cols-3" : "sm:grid-cols-4";
  return (
    <div role="radiogroup" aria-label={label} className={`grid grid-cols-2 gap-2 ${columns}`}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => {
            onChange(o.value);
          }}
          className={`rounded-xl border px-3 py-2.5 text-left transition focus-visible:outline-2 focus-visible:outline-sun-500 ${
            value === o.value
              ? "border-stone-900 bg-stone-900 text-white dark:border-sun-500 dark:bg-sun-500/15 dark:text-sun-200"
              : "border-stone-200 bg-white hover:border-stone-300 dark:border-stone-700 dark:bg-stone-950 dark:hover:border-stone-600"
          }`}
        >
          <span className="block text-sm font-medium">{o.label}</span>
          {o.hint && <span className={`block text-xs ${value === o.value ? "text-stone-300 dark:text-sun-300/80" : "text-stone-500"}`}>{o.hint}</span>}
        </button>
      ))}
    </div>
  );
}

/** A modal dialog (native <dialog> via showModal: focus trap, Escape, backdrop). */
export function Dialog({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean; // side-by-side content (a comparison)
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      onClose={onClose}
      className={`m-auto ${wide ? "w-[min(56rem,calc(100%-2rem))]" : "w-[min(32rem,calc(100%-2rem))]"} rounded-2xl border border-stone-200 bg-white p-0 text-stone-900 shadow-lift backdrop:bg-stone-950/30 backdrop:backdrop-blur-sm dark:border-stone-700 dark:bg-stone-900 dark:text-stone-100`}
    >
      {open && (
        <div className="p-6">
          <h2 className="font-display text-xl font-medium">{title}</h2>
          <div className="mt-3">{children}</div>
        </div>
      )}
    </dialog>
  );
}
