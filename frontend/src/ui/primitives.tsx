import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "accent";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-stone-900 text-white shadow-soft hover:bg-stone-800 disabled:bg-stone-300 dark:bg-stone-100 dark:text-stone-900 dark:hover:bg-white dark:disabled:bg-stone-700 dark:disabled:text-stone-400",
  secondary:
    "border border-stone-200 bg-white text-stone-800 shadow-soft hover:bg-stone-50 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-100 dark:hover:bg-stone-800",
  ghost: "text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100",
  danger: "border border-rose-200 bg-white text-rose-700 hover:bg-rose-50 dark:border-rose-900 dark:bg-stone-900 dark:text-rose-300 dark:hover:bg-rose-950",
  accent: "bg-brand text-white shadow-soft hover:brightness-105 disabled:opacity-50",
};

const SIZES: Record<Size, string> = { sm: "h-8 px-3 text-[13px]", md: "h-10 px-4 text-sm" };

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button
      type="button"
      className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-xl font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sun-500 disabled:cursor-not-allowed ${SIZES[size]} ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

type Tone = "stone" | "green" | "amber" | "rose" | "sun" | "blue";
const TONES: Record<Tone, string> = {
  stone: "bg-stone-100 text-stone-700 ring-stone-200 dark:bg-stone-800 dark:text-stone-300 dark:ring-stone-700",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:ring-emerald-900",
  amber: "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:ring-amber-900",
  rose: "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-950/50 dark:text-rose-300 dark:ring-rose-900",
  sun: "bg-sun-50 text-sun-700 ring-sun-200 dark:bg-sun-700/15 dark:text-sun-300 dark:ring-sun-700/40",
  blue: "bg-sky-50 text-sky-700 ring-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:ring-sky-900",
};

export function Pill({ children, tone = "stone", className = "" }: { children: ReactNode; tone?: Tone; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]} ${className}`}>
      {children}
    </span>
  );
}

export function Spinner({ label, className = "" }: { label?: string; className?: string }) {
  return (
    <span role="status" className={`inline-flex items-center gap-2 text-sm text-stone-500 dark:text-stone-400 ${className}`}>
      <Loader2 aria-hidden className="size-4 animate-spin motion-reduce:animate-none" />
      {label ?? <span className="sr-only">Loading</span>}
    </span>
  );
}

/** Animated dots: the assistant is composing. */
export function Typing({ label }: { label: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2.5 text-sm text-stone-500 dark:text-stone-400">
      <span aria-hidden className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="size-1.5 animate-bounce rounded-full bg-sun-500 motion-reduce:animate-none"
            style={{ animationDelay: `${String(i * 140)}ms` }}
          />
        ))}
      </span>
      {label}
    </span>
  );
}

/** JSON (or text) from a tool: untrusted, so always shown as text, never as markup. */
export function DataBlock({ value }: { value: unknown }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <pre className="scrollbar-thin max-h-64 overflow-auto rounded-lg bg-stone-50 p-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-stone-700 ring-1 ring-stone-200 ring-inset dark:bg-stone-950 dark:text-stone-300 dark:ring-stone-800">
      {text}
    </pre>
  );
}

const AVATAR_TONES = [
  "from-amber-300 to-orange-500",
  "from-rose-300 to-pink-500",
  "from-sky-300 to-indigo-500",
  "from-emerald-300 to-teal-600",
  "from-violet-300 to-purple-600",
  "from-lime-300 to-green-600",
];

/** A stable, friendly avatar for an agent or helper: its initial on a gradient. */
export function Avatar({ name, size = "md", brand = false }: { name: string; size?: "sm" | "md" | "lg"; brand?: boolean }) {
  let hash = 0;
  for (const c of name) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
  const sizes = { sm: "size-6 text-[11px] rounded-lg", md: "size-8 text-sm rounded-xl", lg: "size-12 text-lg rounded-2xl" };
  const tone = brand ? "bg-brand" : `bg-gradient-to-br ${AVATAR_TONES[hash % AVATAR_TONES.length] ?? ""}`;
  return (
    <span aria-hidden className={`inline-flex shrink-0 items-center justify-center font-semibold text-white shadow-soft ${sizes[size]} ${tone}`}>
      {name.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}
