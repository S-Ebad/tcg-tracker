import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { cad, getSets, type SetSummary } from "@/lib/api";

export const metadata: Metadata = { title: "Sets" };

export default function SetsPage() {
  return (
    <div className="mx-auto grid max-w-6xl grid-cols-1 gap-6 px-4 py-6">
      <div className="grid gap-1">
        <h1 className="text-2xl font-bold tracking-tight">Sets</h1>
        <p className="text-sm text-muted-foreground">Every set with singles in stock, A–Z.</p>
      </div>
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <SetIndex />
      </Suspense>
    </div>
  );
}

const letterOf = (s: SetSummary) => {
  const c = (s.set_name ?? s.set_code)[0].toUpperCase();
  return /[A-Z]/.test(c) ? c : "#";
};

async function SetIndex() {
  const sets = await getSets();
  const groups = new Map<string, SetSummary[]>();
  for (const s of sets) groups.set(letterOf(s), [...(groups.get(letterOf(s)) ?? []), s]);
  const letters = [...groups.keys()].sort((a, b) => (a === "#" ? -1 : b === "#" ? 1 : a.localeCompare(b)));

  return (
    <>
      <nav aria-label="Jump to letter" className="flex flex-wrap gap-1">
        {letters.map((l) => (
          <a key={l} href={`#letter-${l}`} className="grid size-8 place-items-center rounded-md border text-sm hover:bg-muted">
            {l}
          </a>
        ))}
      </nav>
      {letters.map((l) => (
        <section key={l} id={`letter-${l}`} className="grid scroll-mt-20 gap-2">
          <h2 className="text-lg font-semibold">{l}</h2>
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {groups.get(l)!.map((s) => (
              <li key={s.set_code}>
                <Link
                  href={`/sets/${encodeURIComponent(s.set_code)}`}
                  className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2 hover:bg-muted/50"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{s.set_name ?? s.set_code}</span>
                    <span className="text-xs text-muted-foreground">
                      {s.set_code} · {s.cards_in_stock} in stock
                    </span>
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground tabular-nums">from {cad(s.cheapest)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}
