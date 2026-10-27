"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import type { Printing } from "@/lib/api";
import { cad, cardHref, imageSrc } from "@/lib/format";
import { cn } from "@/lib/utils";

const MIN_CHARS = 2;
const DEBOUNCE_MS = 200;
const MAX_SUGGESTIONS = 8;

// A GET form to /search (works without JavaScript, shareable URLs) with suggestions as you type: the best-matching
// printings from the API's search. Arrow keys move through them, Enter opens one (or searches when none is picked),
// Escape closes the list.
export function SearchBox({ variant = "default", defaultValue }: { variant?: "default" | "hero"; defaultValue?: string }) {
  const hero = variant === "hero";
  const router = useRouter();
  const listId = useId();
  const [query, setQuery] = useState(defaultValue ?? "");
  const [items, setItems] = useState<Printing[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const boxRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < MIN_CHARS) return;
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const qs = new URLSearchParams({ q, limit: String(MAX_SUGGESTIONS) });
        const res = await fetch(`/api/search?${qs}`, { signal: ctrl.signal });
        if (!res.ok) return;
        const data: { items: Printing[] } = await res.json();
        setItems(data.items);
        setActive(-1);
      } catch {
        // aborted by a newer keystroke, or offline: keep the last suggestions
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [query]);

  // close when focus or a click leaves the box
  useEffect(() => {
    const onDown = (e: PointerEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, []);

  const shown = open && query.trim().length >= MIN_CHARS && items.length > 0;
  const go = (p: Printing) => {
    setOpen(false);
    router.push(cardHref(p.card_key));
  };

  return (
    <form action="/search" role="search" className="relative" ref={boxRef}>
      <Search
        aria-hidden
        className={cn("absolute top-1/2 left-3 size-4 -translate-y-1/2", hero ? "text-white/60" : "text-muted-foreground")}
      />
      <input
        name="q"
        type="search"
        required
        maxLength={100}
        autoComplete="off"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (!shown) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((i) => (i + 1) % items.length);
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((i) => (i <= 0 ? items.length - 1 : i - 1));
          } else if (e.key === "Enter" && active >= 0) {
            e.preventDefault();
            go(items[active]);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        placeholder="Card name or number, e.g. Maxx C or MAMO-EN001"
        aria-label="Search cards"
        role="combobox"
        aria-expanded={shown}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={shown && active >= 0 ? `${listId}-${active}` : undefined}
        className={cn(
          "w-full rounded-lg pr-3 pl-9 outline-none",
          hero
            ? "h-11 bg-white/10 text-white ring-1 ring-white/20 placeholder:text-white/60 focus-visible:ring-2 focus-visible:ring-violet-300"
            : "h-9 bg-background text-sm ring-1 ring-border placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-primary",
        )}
      />
      {shown && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Suggestions"
          className="absolute top-full right-0 left-0 z-50 mt-1 max-h-96 overflow-y-auto rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg"
        >
          {items.map((p, i) => (
            <li
              key={p.card_key}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onPointerDown={(e) => e.preventDefault()} // keep focus in the input until the click lands
              onClick={() => go(p)}
              onPointerEnter={() => setActive(i)}
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5",
                i === active && "bg-muted",
              )}
            >
              <span className="aspect-[59/86] w-8 shrink-0 overflow-hidden rounded-sm bg-muted">
                {/* eslint-disable-next-line @next/next/no-img-element -- our API already serves a resized copy */}
                <img src={imageSrc(p.card_key)} alt="" loading="lazy" className="h-full w-full object-contain" />
              </span>
              <span className="grid min-w-0 flex-1">
                <span className="truncate text-sm font-medium">{p.name}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {p.card_number} · {p.rarity}
                  {p.art_label ? ` · ${p.art_label}` : ""}
                </span>
              </span>
              <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                {p.min_price == null ? "" : cad(p.min_price)}
              </span>
            </li>
          ))}
          <li role="presentation" className="border-t px-2 pt-1.5 pb-1 text-xs text-muted-foreground">
            Press Enter to see all results
          </li>
        </ul>
      )}
    </form>
  );
}
