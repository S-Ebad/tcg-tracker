import type { Metadata } from "next";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { getStores } from "@/lib/api";

export const metadata: Metadata = { title: "Stores" };

const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString("en-CA", {
    timeZone: "America/Toronto",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

export default function StoresPage() {
  return (
    <div className="mx-auto grid max-w-4xl grid-cols-1 gap-6 px-4 py-6">
      <div className="grid gap-2">
        <h1 className="text-2xl font-bold tracking-tight">Stores</h1>
        <p className="text-sm text-muted-foreground">
          We check each store&apos;s in-stock Yu-Gi-Oh! singles twice a day and compare the same printing, edition and
          condition across stores. Buying happens on the store&apos;s own site: every price links to it.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <StoreList />
      </Suspense>
      <p className="rounded-xl border bg-muted/40 p-4 text-sm">
        Thank you to each of these stores for letting us list their prices. A store only appears while we have a
        complete, recent check of its stock, so the prices here are never more than a few days old.
      </p>
    </div>
  );
}

async function StoreList() {
  const stores = await getStores();
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {stores.map((s) => (
        <li key={s.slug} className="grid gap-3 rounded-xl border p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="font-semibold">{s.name}</h2>
              <p className="truncate text-xs text-muted-foreground">{new URL(s.base_url).host}</p>
            </div>
            <a
              href={s.base_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-8 shrink-0 items-center gap-1 rounded-full border px-3 text-xs hover:bg-muted"
            >
              Visit <ExternalLink className="size-3" />
            </a>
          </div>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">Listings in stock</dt>
              <dd className="font-semibold tabular-nums">{s.listings_in_stock.toLocaleString("en-CA")}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Last checked</dt>
              <dd className="font-semibold">{s.last_updated ? fmtTime(s.last_updated) : "–"}</dd>
            </div>
          </dl>
          <Link
            href={`/deals?store=${encodeURIComponent(s.slug)}`}
            className="w-fit text-sm text-primary underline-offset-4 hover:underline"
          >
            Best deals at {s.name} →
          </Link>
        </li>
      ))}
    </ul>
  );
}
