// Typed client for the read-only FastAPI backend (api/ in the repo root). Only server components call it; the browser
// loads card images through the /images rewrite in next.config.ts, so the API never needs to be public.
import { cacheLife } from "next/cache";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type Store = {
  slug: string;
  name: string;
  base_url: string;
  last_updated: string | null;
  listings_in_stock: number;
};

export type Printing = {
  card_key: string;
  name: string;
  card_number: string;
  set_code: string;
  set_name: string | null;
  rarity: string;
  art_label: string | null;
  min_price: number | null;
  store_count: number;
};

export type SetSummary = { set_code: string; set_name: string | null; cards_in_stock: number; cheapest: number };

export type Deal = {
  card_key: string;
  name: string;
  card_number: string;
  rarity: string;
  art_label: string | null;
  edition: string;
  condition: string;
  cheapest_store: string;
  low: number;
  priciest_store: string;
  high: number;
  stores: number;
  saving: number;
  saving_pct: number;
};

export type Offer = {
  store: string;
  store_name: string;
  edition: string | null;
  condition: string | null;
  price: number;
  quantity: number | null;
  in_stock: boolean;
  url: string;
  last_seen: string;
};

export type CardDetail = {
  card_key: string;
  name: string;
  card_number: string;
  set_code: string;
  set_name: string | null;
  rarity: string;
  art_label: string | null;
  editions: (string | null)[];
  cheapest_nm: number | null;
  stores_in_stock: number;
  offers: Offer[];
  other_printings: { card_key: string; card_number: string; rarity: string; art_label: string | null; min_price: number | null }[];
};

export type HistoryPoint = {
  edition: string | null;
  condition: string | null;
  observed_at: string;
  price: number;
  in_stock: boolean;
  source: string;
};
export type HistorySeries = { store: string; points: HistoryPoint[] };

type Params = Record<string, string | number | boolean | undefined>;

async function get<T>(path: string, params: Params = {}): Promise<T> {
  "use cache";
  cacheLife("minutes"); // prices change twice a day; a few minutes old is fine
  const qs = new URLSearchParams(
    Object.entries(params).flatMap(([k, v]) => (v === undefined || v === "" ? [] : [[k, String(v)]])),
  );
  const res = await fetch(`${API_URL}${path}${qs.size ? `?${qs}` : ""}`);
  if (res.status === 404) return null as T; // unknown card: the page shows notFound()
  if (!res.ok) throw new Error(`API ${path} answered ${res.status}`);
  return res.json() as Promise<T>;
}

export const getStores = () => get<Store[]>("/api/stores");
export const getSets = () => get<SetSummary[]>("/api/sets");
export const getDeals = (params: Params = {}) => get<Deal[]>("/api/deals", params);
export const getCard = (key: string) => get<CardDetail | null>(`/api/cards/${encodeURIComponent(key)}`);
export const getHistory = (key: string) => get<HistorySeries[]>(`/api/cards/${encodeURIComponent(key)}/history`);
export const searchPrintings = (params: Params) => get<{ total: number; items: Printing[] }>("/api/search", params);

export { cad, cardHref, CONDITION_NAMES, imageSrc } from "@/lib/format";
