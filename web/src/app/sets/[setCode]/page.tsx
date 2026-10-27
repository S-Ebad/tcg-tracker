import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { CardTile } from "@/components/card-tile";
import { PillMenu } from "@/components/pill-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { getSetPrintings, getSets, getStores, type Printing } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  params: Promise<{ setCode: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

const SORTS = [
  { value: "number", label: "Card number" },
  { value: "price", label: "Lowest price" },
  { value: "name", label: "Name A–Z" },
  { value: "stores", label: "Most stores" },
];
const PAGE = 96;
const API_MAX = 500; // the API's page limit for a set

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
const codeFrom = async (params: Props["params"]) => decodeURIComponent((await params).setCode).toUpperCase();

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const code = await codeFrom(params);
  const set = (await getSets()).find((s) => s.set_code === code);
  return { title: set?.set_name ? `${set.set_name} (${code})` : code };
}

export default function SetPage(props: Props) {
  return (
    <div className="mx-auto grid max-w-6xl grid-cols-1 gap-6 px-4 py-6">
      <Suspense fallback={<GridSkeleton />}>
        <SetBody {...props} />
      </Suspense>
    </div>
  );
}

// every printing of the set (no rarity filter), to list the rarities it has
async function allPrintings(code: string, inStock: boolean): Promise<Printing[]> {
  const first = await getSetPrintings(code, { in_stock: inStock, limit: API_MAX });
  const rest = [];
  for (let offset = API_MAX; offset < first.total; offset += API_MAX) {
    rest.push(getSetPrintings(code, { in_stock: inStock, limit: API_MAX, offset }));
  }
  return [...first.items, ...(await Promise.all(rest)).flatMap((r) => r.items)];
}

async function SetBody({ params, searchParams }: Props) {
  const code = await codeFrom(params);
  const sp = await searchParams;
  const sort = SORTS.some((s) => s.value === one(sp.sort)) ? one(sp.sort) : "number";
  const rarity = one(sp.rarity);
  const store = one(sp.store);
  const inStock = one(sp.in_stock) !== "0";
  const page = Math.max(1, Number.parseInt(one(sp.page), 10) || 1);

  const [sets, stores, all, shown] = await Promise.all([
    getSets(),
    getStores(),
    allPrintings(code, inStock),
    getSetPrintings(code, {
      sort,
      rarity: rarity || undefined,
      store: store || undefined,
      in_stock: inStock,
      limit: PAGE,
      offset: (page - 1) * PAGE,
    }),
  ]);
  const set = sets.find((s) => s.set_code === code);
  if (!set && all.length === 0) notFound();
  const name = set?.set_name ?? all[0]?.set_name ?? code;
  const rarities = [...new Set(all.map((p) => p.rarity))].sort();

  // link to this page with some settings changed; any change goes back to page 1, defaults stay out of the URL
  const href = (over: { sort?: string; rarity?: string; store?: string; in_stock?: string; page?: string }) => {
    const next = { sort, rarity, store, in_stock: inStock ? "" : "0", page: "", ...over };
    if (next.sort === "number") next.sort = "";
    const qs = new URLSearchParams(Object.entries(next).filter(([, v]) => v)).toString();
    return `/sets/${encodeURIComponent(code)}${qs ? `?${qs}` : ""}`;
  };

  return (
    <>
      <div className="grid gap-1">
        <Link href="/sets" className="w-fit text-sm text-muted-foreground hover:text-foreground">
          ← All sets
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">{name}</h1>
        <p className="text-sm text-muted-foreground">
          <span className="font-mono">{code}</span> · {(set?.cards_in_stock ?? all.length).toLocaleString("en-CA")}{" "}
          printings in stock
        </p>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
        <PillMenu
          label="Sort"
          options={SORTS.map((s) => ({ label: s.label, href: href({ sort: s.value }), active: s.value === sort }))}
        />
        <PillMenu
          label="Rarity"
          filled={!!rarity}
          options={[
            { label: "All", href: href({ rarity: "" }), active: !rarity },
            ...rarities.map((r) => ({ label: r, href: href({ rarity: r }), active: r === rarity })),
          ]}
        />
        <PillMenu
          label="Store"
          filled={!!store}
          options={[
            { label: "All", href: href({ store: "" }), active: !store },
            ...stores.map((s) => ({ label: s.name, href: href({ store: s.slug }), active: s.slug === store })),
          ]}
        />
        <Link
          href={href({ in_stock: inStock ? "0" : "" })}
          className={cn(
            "inline-flex h-8 shrink-0 items-center rounded-full border px-3 text-sm",
            inStock ? "border-transparent bg-secondary font-medium" : "hover:bg-muted",
          )}
        >
          {inStock ? "✓ In stock only" : "Including sold out"}
        </Link>
      </div>

      {shown.items.length === 0 ? (
        <p className="text-muted-foreground">No cards match these filters.</p>
      ) : (
        <div className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {shown.items.map((p) => (
            <CardTile key={p.card_key} p={p} />
          ))}
        </div>
      )}

      {shown.total > PAGE && (
        <nav className="flex items-center justify-center gap-3 text-sm">
          {page > 1 && (
            <Link href={href({ page: String(page - 1) })} className="rounded-full border px-3 py-1.5 hover:bg-muted">
              Previous
            </Link>
          )}
          <span className="text-muted-foreground">
            Page {page} of {Math.ceil(shown.total / PAGE)}
          </span>
          {page * PAGE < shown.total && (
            <Link href={href({ page: String(page + 1) })} className="rounded-full border px-3 py-1.5 hover:bg-muted">
              Next
            </Link>
          )}
        </nav>
      )}
    </>
  );
}

function GridSkeleton() {
  return (
    <div className="grid gap-6">
      <Skeleton className="h-16 w-2/3" />
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {Array.from({ length: 12 }, (_, i) => (
          <Skeleton key={i} className="aspect-[59/86] w-full" />
        ))}
      </div>
    </div>
  );
}
