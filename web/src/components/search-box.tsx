import { Search } from "lucide-react";

import { cn } from "@/lib/utils";

// A plain GET form: works without JavaScript and gives /search?q=... URLs people can share.
export function SearchBox({ variant = "default", defaultValue }: { variant?: "default" | "hero"; defaultValue?: string }) {
  const hero = variant === "hero";
  return (
    <form action="/search" role="search" className="relative">
      <Search
        aria-hidden
        className={cn("absolute top-1/2 left-3 size-4 -translate-y-1/2", hero ? "text-white/60" : "text-muted-foreground")}
      />
      <input
        name="q"
        type="search"
        required
        maxLength={100}
        defaultValue={defaultValue}
        placeholder="Card name or number, e.g. Maxx C or MAMO-EN001"
        aria-label="Search cards"
        className={cn(
          "w-full rounded-lg pr-3 pl-9 outline-none",
          hero
            ? "h-11 bg-white/10 text-white ring-1 ring-white/20 placeholder:text-white/60 focus-visible:ring-2 focus-visible:ring-violet-300"
            : "h-9 bg-background text-sm ring-1 ring-border placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-primary",
        )}
      />
    </form>
  );
}
