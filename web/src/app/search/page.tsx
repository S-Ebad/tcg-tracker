import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { CardTile } from "@/components/card-tile";
import { Skeleton } from "@/components/ui/skeleton";
import { searchPrintings } from "@/lib/api";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Search" };

const SORTS = [
  { value: "best", label: "Best match" },
  { value: "price", label: "Lowest price" },
  { value: "stores", label: "Most stores" },
  { value: "name", label: "Name A–Z" },
];
const PAGE = 24;

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default function SearchPage({ searchParams }: Props) {
  return (
    <div className="mx-auto grid max-w-6xl grid-cols-1 gap-6 px-4 py-6">
      <Suspense fallback={<ResultsSkeleton />}>
        <Results searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";

async function Results({ searchParams }: Props) {
  const sp = await searchParams;
  const q = one(sp.q).trim().slice(0, 100);
  const sort = SORTS.some((s) => s.value === one(sp.sort)) ? one(sp.sort) : "best";
  const page = Math.max(1, Number.parseInt(one(sp.page), 10) || 1);
  if (!q) return <p className="text-muted-foreground">Type a card name or number to search.</p>;

  const { total, items } = await searchPrintings({ q, sort, limit: PAGE, offset: (page - 1) * PAGE });
  const link = (over: { sort?: string; page?: number }) =>
    `/search?${new URLSearchParams({ q, sort: over.sort ?? sort, page: String(over.page ?? 1) })}`;

  return (
    <>
      <div className="grid gap-3">
        <h1 className="text-xl font-semibold">
          {total.toLocaleString("en-CA")} result{total === 1 ? "" : "s"} for “{q}”
        </h1>
        <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
          {SORTS.map((s) => (
            <Link
              key={s.value}
              href={link({ sort: s.value })}
              className={cn(
                "inline-flex h-8 shrink-0 items-center rounded-full border px-3 text-sm",
                s.value === sort ? "border-transparent bg-secondary font-medium" : "hover:bg-muted",
              )}
            >
              {s.label}
            </Link>
          ))}
        </div>
      </div>
      {items.length === 0 ? (
        <p className="text-muted-foreground">
          No in-stock cards match. Try fewer words or a card number like MAMO-EN001.
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {items.map((p) => (
            <CardTile key={p.card_key} p={p} />
          ))}
        </div>
      )}
      {total > PAGE && (
        <nav className="flex items-center justify-center gap-3 text-sm">
          {page > 1 && (
            <Link href={link({ page: page - 1 })} className="rounded-full border px-3 py-1.5 hover:bg-muted">
              Previous
            </Link>
          )}
          <span className="text-muted-foreground">
            Page {page} of {Math.ceil(total / PAGE)}
          </span>
          {page * PAGE < total && (
            <Link href={link({ page: page + 1 })} className="rounded-full border px-3 py-1.5 hover:bg-muted">
              Next
            </Link>
          )}
        </nav>
      )}
    </>
  );
}

function ResultsSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
      {Array.from({ length: 12 }, (_, i) => (
        <Skeleton key={i} className="aspect-[59/86] w-full" />
      ))}
    </div>
  );
}
