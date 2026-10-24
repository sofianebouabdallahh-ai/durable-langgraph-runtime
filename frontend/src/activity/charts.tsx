/**
 * Small charts for the Activity page, in plain SVG (no chart library).
 *
 * The dataviz method: one axis; thin columns (≤ 24px) with a 4px rounded top, square at
 * the baseline; a 2px surface gap between stacked segments; recessive hairline grid;
 * categorical colour by entity in a fixed order (validated palette, see index.css
 * `--series-*`), never by rank; a legend for two or more series; a tooltip on hover and
 * keyboard focus; and a table view, so nothing depends on colour or on hovering.
 */
import { type RefObject, useId, useLayoutEffect, useRef, useState } from "react";

export interface Column {
  key: string; // the x value (a day)
  label: string; // how it's read ("Oct 21")
  values: Record<string, number>; // series → value
}

export interface Series {
  key: string;
  label: string;
  color: string; // a CSS colour (a --series-* variable)
}

const H = 140; // plot height
const BAR = 24; // max column width
const GAP = 2; // the surface gap between stacked segments
const AXIS = 40; // room for the y labels, left of the plot

/** An element's width in CSS pixels, kept current (the chart is drawn at its real size). */
function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.round(entry.contentRect.width));
    });
    observer.observe(el);
    return () => {
      observer.disconnect();
    };
  }, []);
  return [ref, width];
}

export function compact(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

function niceMax(max: number): number {
  if (max <= 0) return 1;
  const step = 10 ** Math.floor(Math.log10(max));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * step >= max) return m * step;
  return 10 * step;
}

/** Stacked columns (one per day), or plain ones with a single series. */
export function Columns({
  title,
  columns,
  series,
  format = compact,
}: {
  title: string;
  columns: readonly Column[];
  series: readonly Series[];
  format?: (n: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const id = useId();
  const [box, boxWidth] = useWidth<HTMLElement>();
  const totals = columns.map((c) => series.reduce((s, x) => s + (c.values[x.key] ?? 0), 0));
  const max = niceMax(Math.max(0, ...totals));
  const width = Math.max(boxWidth - AXIS, 160); // the plot, in pixels
  const band = width / Math.max(columns.length, 1);
  const bar = Math.min(BAR, band * 0.6);
  const y = (v: number) => H - (v / max) * H;
  const ticks = [0, max / 2, max];
  const shown = hover !== null ? columns[hover] : undefined;

  return (
    <figure ref={box} className="viz min-w-0" aria-labelledby={`${id}-t`}>
      <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span id={`${id}-t`} className="text-sm font-medium text-stone-800 dark:text-stone-200">
          {title}
        </span>
        {series.length > 1 && (
          <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-stone-600 dark:text-stone-400" aria-label="Legend">
            {series.map((s) => (
              <li key={s.key} className="inline-flex items-center gap-1.5">
                <span aria-hidden className="inline-block size-2.5 rounded-sm" style={{ background: s.color }} />
                {s.label}
              </li>
            ))}
          </ul>
        )}
        <button
          type="button"
          onClick={() => {
            setTable(!table);
          }}
          className="ml-auto text-xs text-stone-500 underline-offset-2 hover:underline"
          aria-pressed={table}
        >
          {table ? "Show the chart" : "Show as a table"}
        </button>
      </figcaption>
      {table ? (
        <table className="mt-2 w-full text-left text-xs tabular-nums">
          <thead className="text-stone-500">
            <tr>
              <th className="py-1 font-medium">Day</th>
              {series.map((s) => (
                <th key={s.key} className="py-1 text-right font-medium">
                  {s.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {columns.map((c) => (
              <tr key={c.key} className="border-t border-stone-100 dark:border-stone-800">
                <td className="py-1">{c.label}</td>
                {series.map((s) => (
                  <td key={s.key} className="py-1 text-right">
                    {format(c.values[s.key] ?? 0)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : columns.length === 0 ? (
        <p className="mt-6 mb-4 text-sm text-stone-500">Nothing in this range yet.</p>
      ) : (
        <div className="relative mt-2">
          <svg width={width + AXIS} height={H + 30} viewBox={`${String(-AXIS)} -8 ${String(width + AXIS)} ${String(H + 30)}`} className="block" role="img" aria-label={title}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={0} x2={width} y1={y(t)} y2={y(t)} className="stroke-stone-200 dark:stroke-stone-800" strokeWidth={1} />
                <text x={-6} y={y(t) + 4} textAnchor="end" className="fill-stone-500 text-[11px] tabular-nums">
                  {format(t)}
                </text>
              </g>
            ))}
            {columns.map((c, i) => {
              const x = i * band + (band - bar) / 2;
              let top = H;
              const visible = series.filter((s) => (c.values[s.key] ?? 0) > 0);
              return (
                <g
                  key={c.key}
                  tabIndex={0}
                  role="img"
                  aria-label={`${c.label}: ${series.map((s) => `${s.label} ${format(c.values[s.key] ?? 0)}`).join(", ")}`}
                  onPointerEnter={() => {
                    setHover(i);
                  }}
                  onPointerLeave={() => {
                    setHover(null);
                  }}
                  onFocus={() => {
                    setHover(i);
                  }}
                  onBlur={() => {
                    setHover(null);
                  }}
                  className="outline-none"
                >
                  <rect x={i * band} y={-8} width={band} height={H + 8} fill="transparent" />
                  {visible.map((s, j) => {
                    const h = ((c.values[s.key] ?? 0) / max) * H;
                    const last = j === visible.length - 1;
                    const segH = Math.max(h - (last ? 0 : GAP), 1);
                    top -= h;
                    const yTop = top + (last ? 0 : GAP);
                    return last ? (
                      <path key={s.key} d={roundedTop(x, yTop, bar, segH, 4)} style={{ fill: s.color, opacity: hover === null || hover === i ? 1 : 0.55 }} />
                    ) : (
                      <rect key={s.key} x={x} y={yTop} width={bar} height={segH} style={{ fill: s.color, opacity: hover === null || hover === i ? 1 : 0.55 }} />
                    );
                  })}
                  {i % Math.max(1, Math.ceil((columns.length * 56) / width)) === 0 && (
                    <text x={x + bar / 2} y={H + 16} textAnchor="middle" className="fill-stone-500 text-[11px]">
                      {c.label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
          {shown && (
            <div
              role="status"
              className="pointer-events-none absolute top-0 rounded-lg bg-white px-2.5 py-1.5 text-xs shadow-lift ring-1 ring-stone-200 dark:bg-stone-900 dark:ring-stone-700"
              style={{ left: `${String(Math.min(AXIS + ((hover ?? 0) + 0.5) * band + 8, Math.max(0, width + AXIS - 170)))}px` }}
            >
              <div className="mb-1 text-stone-500">{shown.label}</div>
              {series.map((s) => (
                <div key={s.key} className="flex items-center gap-2 tabular-nums">
                  <span aria-hidden className="inline-block h-0.5 w-3 rounded" style={{ background: s.color }} />
                  <span className="font-semibold text-stone-900 dark:text-stone-100">{format(shown.values[s.key] ?? 0)}</span>
                  <span className="text-stone-500">{s.label}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </figure>
  );
}

/** A column with a 4px rounded top and a square base. */
function roundedTop(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.min(r, w / 2, h);
  return `M${String(x)},${String(y + h)}V${String(y + rr)}Q${String(x)},${String(y)} ${String(x + rr)},${String(y)}H${String(x + w - rr)}Q${String(x + w)},${String(y)} ${String(x + w)},${String(y + rr)}V${String(y + h)}Z`;
}

/** A thin bar for a table cell: a share of the largest value, one series colour. */
export function Meter({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <span className="inline-block h-1.5 w-20 rounded-full bg-[var(--series-track)] align-middle" role="img" aria-label={label}>
      <span className="block h-1.5 rounded-full bg-[var(--series-1)]" style={{ width: `${String(pct)}%` }} />
    </span>
  );
}
