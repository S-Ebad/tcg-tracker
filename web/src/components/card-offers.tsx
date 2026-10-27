"use client";

import { ExternalLink } from "lucide-react";
import { useState } from "react";

import { PriceChart } from "@/components/price-chart";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { CardDetail, HistorySeries } from "@/lib/api";
import { cad, CONDITION_NAMES } from "@/lib/format";
import { cn } from "@/lib/utils";

const editionLabel = (e: string | null) => e ?? "Edition not listed";
const tabValue = (e: string | null) => e ?? "unknown";

// Edition tabs -> price table for that edition, and a price history chart for one condition of it.
export function CardOffers({ card, history }: { card: CardDetail; history: HistorySeries[] }) {
  const [edition, setEdition] = useState<string | null>(card.editions[0] ?? null);
  const offers = card.offers.filter((o) => o.edition === edition);
  const conditions = [...new Set(offers.map((o) => o.condition))];
  const [condition, setCondition] = useState<string | null>(conditions[0] ?? null);
  const chartCondition = conditions.includes(condition) ? condition : (conditions[0] ?? null);

  const asOf = Math.max(...card.offers.map((o) => new Date(o.last_seen).getTime()));
  // cheapest in-stock offer per condition gets the badge
  const cheapest = new Map<string | null, number>();
  for (const o of offers) {
    if (o.in_stock && o.price < (cheapest.get(o.condition) ?? Infinity)) cheapest.set(o.condition, o.price);
  }

  return (
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Prices</h2>
        {card.editions.length > 1 ? (
          <Tabs
            value={tabValue(edition)}
            onValueChange={(v) => setEdition(card.editions.find((e) => tabValue(e) === v) ?? null)}
          >
            <TabsList>
              {card.editions.map((e) => (
                <TabsTrigger key={tabValue(e)} value={tabValue(e)} className="px-3">
                  {editionLabel(e)}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        ) : (
          <Badge variant="secondary">{editionLabel(edition)}</Badge>
        )}
      </div>

      {offers.length === 0 ? (
        <p className="text-sm text-muted-foreground">No store lists this printing right now.</p>
      ) : (
        <div className="overflow-hidden rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Store</th>
                <th className="px-3 py-2 font-medium">Condition</th>
                <th className="px-3 py-2 text-right font-medium">Price</th>
                <th className="w-0 px-3 py-2">
                  <span className="sr-only">Link</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {offers.map((o, i) => {
                const best = o.in_stock && cheapest.get(o.condition) === o.price;
                return (
                  <tr key={i} className={cn("border-t", !o.in_stock && "text-muted-foreground")}>
                    <td className="px-3 py-2.5 font-medium">{o.store_name}</td>
                    <td className="px-3 py-2.5">
                      <span className="sm:hidden" title={CONDITION_NAMES[o.condition ?? ""]}>
                        {o.condition ?? "?"}
                      </span>
                      <span className="hidden sm:inline">{CONDITION_NAMES[o.condition ?? ""] ?? "Unknown"}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                        {best && <Badge className="text-[10px]">Cheapest</Badge>}
                        {o.in_stock ? (
                          <span className="font-semibold">{cad(o.price)}</span>
                        ) : (
                          <span>Sold out</span>
                        )}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <a
                        href={o.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`View at ${o.store_name}`}
                        className="inline-flex h-8 items-center gap-1 rounded-full border px-2.5 text-xs whitespace-nowrap hover:bg-muted"
                      >
                        Visit <ExternalLink className="size-3" />
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">Price history</h2>
          <div className="flex gap-1.5 overflow-x-auto [scrollbar-width:none]">
            {conditions.map((c) => (
              <button
                key={c ?? "?"}
                type="button"
                onClick={() => setCondition(c)}
                className={cn(
                  "h-8 shrink-0 rounded-full border px-3 text-xs",
                  c === chartCondition ? "border-transparent bg-secondary font-medium" : "hover:bg-muted",
                )}
              >
                {c ?? "?"}
              </button>
            ))}
          </div>
        </div>
        <PriceChart history={history} edition={edition} condition={chartCondition} asOf={asOf} />
      </div>
    </section>
  );
}
