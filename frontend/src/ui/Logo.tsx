import { useId } from "react";

/** The Nuria mark: an "N" drawn as one stroke, ending in a point of light. */
export function Mark({ size = 28, className = "" }: { size?: number; className?: string }) {
  // Each instance its own gradient id: a duplicate id resolves to the first element,
  // which may sit in a hidden part of the page (the desktop sidebar on a phone).
  const id = useId();
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className={className}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffb347" />
          <stop offset=".48" stopColor="#fd7a10" />
          <stop offset="1" stopColor="#e8475f" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${id})`} />
      <path d="M10 22V10l12 12V10" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="22" cy="10" r="2.2" fill="#fff" />
    </svg>
  );
}

export function Logo() {
  return (
    <span className="flex items-center gap-2.5">
      <Mark />
      <span className="font-display text-[1.35rem] font-semibold tracking-tight">Nuria</span>
    </span>
  );
}
