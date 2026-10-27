import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { CardOffers } from "@/components/card-offers";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cad, cardHref, getCard, getHistory, getStores, imageSrc } from "@/lib/api";

type Props = { params: Promise<{ cardKey: string }> };

const keyFrom = (raw: string) => {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const card = await getCard(keyFrom((await params).cardKey));
  return { title: card ? `${card.name} (${card.card_number})` : "Card not found" };
}

export default function CardPage({ params }: Props) {
  return (
    <div className="mx-auto grid max-w-6xl grid-cols-1 gap-8 px-4 py-6">
      <Suspense fallback={<CardSkeleton />}>
        <CardBody params={params} />
      </Suspense>
    </div>
  );
}

async function CardBody({ params }: Props) {
  const key = keyFrom((await params).cardKey);
  const [card, history, stores] = await Promise.all([getCard(key), getHistory(key), getStores()]);
  if (!card) notFound();
  const updated = stores
    .filter((s) => card.offers.some((o) => o.store === s.slug) && s.last_updated)
    .map((s) => new Date(s.last_updated!).getTime());
  const lastUpdated = updated.length ? new Date(Math.min(...updated)) : null;

  return (
    <>
      <section className="grid gap-6 sm:grid-cols-[minmax(0,240px)_minmax(0,1fr)]">
        <div className="mx-auto aspect-[59/86] w-48 overflow-hidden rounded-lg bg-muted sm:w-full">
          {/* eslint-disable-next-line @next/next/no-img-element -- our API already serves a resized copy */}
          <img src={imageSrc(card.card_key)} alt={card.name} className="h-full w-full object-contain" />
        </div>
        <div className="grid content-start gap-4">
          <div className="grid gap-2">
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{card.name}</h1>
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <span className="font-mono">{card.card_number}</span>
              <Badge>{card.rarity}</Badge>
              {card.art_label && <Badge variant="secondary">{card.art_label}</Badge>}
            </div>
            {card.set_name && (
              <Link
                href={`/sets/${encodeURIComponent(card.set_code)}`}
                className="w-fit text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
              >
                {card.set_name} ({card.set_code})
              </Link>
            )}
          </div>
          <dl className="grid grid-cols-3 gap-3">
            <Fact label="Cheapest near mint" value={card.cheapest_nm == null ? "–" : cad(card.cheapest_nm)} />
            <Fact label="Stores in stock" value={String(card.stores_in_stock)} />
            <Fact
              label="Prices checked"
              value={lastUpdated ? lastUpdated.toLocaleDateString("en-CA", { month: "short", day: "numeric" }) : "–"}
            />
          </dl>
        </div>
      </section>

      <CardOffers card={card} history={history} />

      {card.other_printings.length > 0 && (
        <section className="grid gap-3">
          <h2 className="text-lg font-semibold">Other printings of {card.name}</h2>
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {card.other_printings.map((p) => (
              <li key={p.card_key}>
                <Link
                  href={cardHref(p.card_key)}
                  className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm hover:bg-muted/50"
                >
                  <span className="min-w-0 truncate">
                    <span className="font-mono">{p.card_number}</span> · {p.rarity}
                    {p.art_label ? ` · ${p.art_label}` : ""}
                  </span>
                  <span className="shrink-0 text-muted-foreground tabular-nums">
                    {p.min_price == null ? "out of stock" : `from ${cad(p.min_price)}`}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function CardSkeleton() {
  return (
    <div className="grid gap-6 sm:grid-cols-[240px_1fr]">
      <Skeleton className="mx-auto aspect-[59/86] w-48 sm:w-full" />
      <div className="grid content-start gap-3">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-5 w-1/2" />
        <Skeleton className="h-20 w-full" />
      </div>
    </div>
  );
}
