import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { PillMenu } from "@/components/pill-menu";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cad, cardHref, CONDITION_NAMES, getDeals, getStores, imageSrc } from "@/lib/api";

export const metadata: Metadata = { title: "Deals" };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

const SORTS = [
  { value: "amount", label: "Biggest saving ($)" },
  { value: "percent", label: "Biggest saving (%)" },
];
const MIN_PRICES = ["0", "5", "20", "50", "100"];
const PAGE = 50;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";

export default function DealsPage({ searchParams }: Props) {
  return (
    <div className="mx-auto grid max-w-4xl grid-cols-1 gap-6 px-4 py-6">
      <div className="grid gap-1">
        <h1 className="text-2xl font-bold tracking-tight">Deals</h1>
        <p className="text-sm text-muted-foreground">
          The same card, edition and condition at two or more stores: what you save buying at the cheapest one
          instead of the priciest.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <DealList searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function DealList({ searchParams }: Props) {
  const sp = await searchParams;
  const sort = SORTS.some((s) => s.value === one(sp.sort)) ? one(sp.sort) : "amount";
  const condition = one(sp.condition) in CONDITION_NAMES ? one(sp.condition) : "NM";
  const minPrice = MIN_PRICES.includes(one(sp.min_price)) ? one(sp.min_price) : "5";
  const store = one(sp.store);
  const page = Math.max(1, Number.parseInt(one(sp.page), 10) || 1);

  const [deals, stores] = await Promise.all([
    getDeals({ sort, condition, min_price: minPrice, store: store || undefined, limit: PAGE, offset: (page - 1) * PAGE }),
    getStores(),
  ]);
  const storeName = Object.fromEntries(stores.map((s) => [s.slug, s.name]));

  // link to this page with some settings changed; any change goes back to page 1, defaults stay out of the URL
  const href = (over: { sort?: string; condition?: string; min_price?: string; store?: string; page?: string }) => {
    const next = { sort, condition, min_price: minPrice, store, page: "", ...over };
    const defaults: Record<string, string> = { sort: "amount", condition: "NM", min_price: "5" };
    const qs = new URLSearchParams(Object.entries(next).filter(([k, v]) => v && v !== defaults[k])).toString();
    return `/deals${qs ? `?${qs}` : ""}`;
  };

  return (
    <>
      <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
        <PillMenu
          label="Sort"
          options={SORTS.map((s) => ({ label: s.label, href: href({ sort: s.value }), active: s.value === sort }))}
        />
        <PillMenu
          label="Condition"
          filled={condition !== "NM"}
          options={Object.entries(CONDITION_NAMES).map(([c, label]) => ({
            label,
            href: href({ condition: c }),
            active: c === condition,
          }))}
        />
        <PillMenu
          label="Price"
          filled={minPrice !== "5"}
          options={MIN_PRICES.map((p) => ({
            label: p === "0" ? "Any" : `$${p}+`,
            href: href({ min_price: p }),
            active: p === minPrice,
          }))}
        />
        <PillMenu
          label="Buy from"
          filled={!!store}
          options={[
            { label: "Any store", href: href({ store: "" }), active: !store },
            ...stores.map((s) => ({ label: s.name, href: href({ store: s.slug }), active: s.slug === store })),
          ]}
        />
      </div>

      {deals.length === 0 ? (
        <p className="text-muted-foreground">No deals match these filters.</p>
      ) : (
        <ol className="grid gap-3">
          {deals.map((d) => (
            <li key={`${d.card_key}|${d.edition}`}>
              <Link
                href={cardHref(d.card_key)}
                className="flex gap-3 rounded-xl border p-3 hover:bg-muted/50"
              >
                <div className="aspect-[59/86] w-14 shrink-0 overflow-hidden rounded bg-muted">
                  {/* eslint-disable-next-line @next/next/no-img-element -- our API already serves a resized copy */}
                  <img src={imageSrc(d.card_key)} alt="" loading="lazy" className="h-full w-full object-contain" />
                </div>
                <div className="grid min-w-0 flex-1 content-start gap-1">
                  <p className="truncate font-medium">{d.name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {d.card_number} · {d.rarity}
                    {d.art_label ? ` · ${d.art_label}` : ""} · {d.edition} · {d.condition}
                  </p>
                  <p className="text-sm">
                    <span className="font-semibold tabular-nums">{cad(d.low)}</span> at {storeName[d.cheapest_store]}{" "}
                    <span className="text-muted-foreground">
                      vs <span className="tabular-nums line-through">{cad(d.high)}</span> at{" "}
                      {storeName[d.priciest_store]}
                    </span>
                  </p>
                </div>
                <div className="grid shrink-0 content-start justify-items-end gap-1 text-right">
                  <Badge>Save {cad(d.saving)}</Badge>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {Math.round(d.saving_pct * 100)}% less
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ol>
      )}

      {(page > 1 || deals.length === PAGE) && (
        <nav className="flex items-center justify-center gap-3 text-sm">
          {page > 1 && (
            <Link href={href({ page: String(page - 1) })} className="rounded-full border px-3 py-1.5 hover:bg-muted">
              Previous
            </Link>
          )}
          <span className="text-muted-foreground">Page {page}</span>
          {deals.length === PAGE && (
            <Link href={href({ page: String(page + 1) })} className="rounded-full border px-3 py-1.5 hover:bg-muted">
              Next
            </Link>
          )}
        </nav>
      )}
    </>
  );
}
