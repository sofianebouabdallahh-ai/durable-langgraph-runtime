/** The Nuria mark: an "N" drawn as one stroke, ending in a point of light. */
export function Mark({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className={className}>
      <defs>
        <linearGradient id="nuria-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffb347" />
          <stop offset=".48" stopColor="#fd7a10" />
          <stop offset="1" stopColor="#e8475f" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#nuria-g)" />
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
