// Display helpers shared by server and client components (lib/api.ts is server-only).

// browser-facing image path (proxied to the API by next.config.ts)
export const imageSrc = (cardKey: string) => `/images/${encodeURIComponent(cardKey)}`;

// as the stores grade them; 401's PL ("played") is its own grade, never merged with LP or MP
export const CONDITION_NAMES: Record<string, string> = {
  NM: "Near Mint",
  LP: "Lightly Played",
  MP: "Moderately Played",
  PL: "Played (PL)",
  HP: "Heavily Played",
  DMG: "Damaged",
};

export const cardHref = (cardKey: string) => `/cards/${encodeURIComponent(cardKey)}`;

export const cad =(n: number | null | undefined) =>
  n == null ? "–" : n.toLocaleString("en-CA", { style: "currency", currency: "CAD" });
