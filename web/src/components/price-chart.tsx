"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { HistorySeries } from "@/lib/api";
import { cad } from "@/lib/format";
import { cn } from "@/lib/utils";

const STORE_STYLE: Record<string, { label: string; color: string }> = {
  trinity: { label: "Trinity Hobby", color: "oklch(0.62 0.19 259)" },
  "401games": { label: "401 Games", color: "oklch(0.70 0.17 50)" },
  hobbiesville: { label: "Hobbiesville", color: "oklch(0.65 0.15 165)" },
  fusion: { label: "Fusion Gaming", color: "oklch(0.63 0.22 350)" },
};
const DAY = 86_400_000;
const fmtDate = (t: number) => new Date(t).toLocaleDateString("en-CA", { month: "short", day: "numeric" });

type Row = { t: number } & Record<string, number | null>;

// Price history stores a row only when a price changes, so each store's price holds until its next point; a sold-out
// point breaks the line. The last known price is carried forward to `asOf` (the newest crawl that saw the card).
function buildRows(
  series: { store: string; points: { t: number; price: number | null }[] }[],
  from: number,
  now: number,
): Row[] {
  const times = [...new Set([from, now, ...series.flatMap((s) => s.points.map((p) => p.t)).filter((t) => t > from)])];
  times.sort((a, b) => a - b);
  return times.map((t) => {
    const row: Row = { t } as Row;
    for (const s of series) {
      const last = s.points.filter((p) => p.t <= t).at(-1);
      row[s.store] = last ? last.price : null;
    }
    return row;
  });
}

export function PriceChart({
  history,
  edition,
  condition,
  asOf,
}: {
  history: HistorySeries[];
  edition: string | null;
  condition: string | null;
  asOf: number;
}) {
  const [range, setRange] = useState<"30d" | "all">("30d");
  const series = history
    .map((s) => ({
      store: s.store,
      points: s.points
        .filter((p) => p.edition === edition && p.condition === condition)
        .map((p) => ({ t: new Date(p.observed_at).getTime(), price: p.in_stock ? p.price : null })),
    }))
    .filter((s) => s.points.length > 0);

  if (series.length === 0) {
    return <p className="text-sm text-muted-foreground">No price history for this edition and condition yet.</p>;
  }
  const first = Math.min(...series.flatMap((s) => s.points.map((p) => p.t)));
  const from = range === "30d" ? Math.max(first, asOf - 30 * DAY) : first;
  const rows = buildRows(series, from, Math.max(asOf, first));
  const config: ChartConfig = Object.fromEntries(
    series.map((s) => [s.store, STORE_STYLE[s.store] ?? { label: s.store, color: "var(--muted-foreground)" }]),
  );

  return (
    <div className="grid gap-2">
      <ChartContainer config={config} className="aspect-auto h-56 w-full sm:h-72">
        <LineChart data={rows} margin={{ left: 4, right: 12, top: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={fmtDate}
            tickLine={false}
            axisLine={false}
            minTickGap={32}
          />
          <YAxis
            width={56}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => `$${v < 100 ? v.toFixed(2) : Math.round(v)}`}
            domain={["auto", "auto"]}
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={(_, payload) => fmtDate(Number(payload?.[0]?.payload?.t))}
                formatter={(value, name) => (
                  <span className="flex w-full justify-between gap-3">
                    <span className="text-muted-foreground">{config[String(name)]?.label}</span>
                    <span className="font-medium tabular-nums">{cad(Number(value))}</span>
                  </span>
                )}
              />
            }
          />
          {series.map((s) => (
            <Line
              key={s.store}
              dataKey={s.store}
              type="stepAfter"
              stroke={`var(--color-${s.store})`}
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ChartContainer>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <div className="flex flex-wrap gap-3">
          {series.map((s) => (
            <span key={s.store} className="inline-flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: config[s.store].color }} />
              {config[s.store].label}
            </span>
          ))}
        </div>
        <div className="flex gap-1">
          {(["30d", "all"] as const).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRange(r)}
              className={cn("h-7 rounded-full border px-2.5", r === range ? "bg-secondary font-medium" : "hover:bg-muted")}
            >
              {r === "30d" ? "30 days" : "All"}
            </button>
          ))}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">Tracking started October 2026; lines fill in as prices change.</p>
    </div>
  );
}
