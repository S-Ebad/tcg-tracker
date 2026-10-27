"use client";

import { ChevronDown } from "lucide-react";
import { useRouter } from "next/navigation";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export type PillOption = { label: string; href: string; active: boolean };

// A pill button that opens a menu of links (sort order, or one filter value). The active option is checked; a
// filter that is set shows the pill filled in.
export function PillMenu({ label, options, filled = false }: { label: string; options: PillOption[]; filled?: boolean }) {
  const router = useRouter();
  const active = options.find((o) => o.active);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          "inline-flex h-8 shrink-0 items-center gap-1 rounded-full border px-3 text-sm",
          filled ? "border-transparent bg-secondary font-medium" : "hover:bg-muted",
        )}
      >
        {label}: {active?.label ?? "All"} <ChevronDown className="size-3.5 opacity-60" />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="max-h-80 min-w-44 overflow-y-auto">
        <DropdownMenuRadioGroup value={active?.href ?? ""} onValueChange={(href: string) => router.push(href)}>
          {options.map((o) => (
            <DropdownMenuRadioItem key={o.href} value={o.href}>
              {o.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
