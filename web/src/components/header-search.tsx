"use client";

import { usePathname } from "next/navigation";

import { SearchBox } from "@/components/search-box";

// On the home page the search box lives in the banner instead.
export function HeaderSearch() {
  if (usePathname() === "/") return null;
  return (
    <div className="w-full sm:ml-auto sm:w-72">
      <SearchBox />
    </div>
  );
}
