import { getStores } from "@/lib/api";

export async function SiteFooter() {
  const stores = await getStores().catch(() => []);
  return (
    <footer className="mt-16 border-t text-sm text-muted-foreground">
      <div className="mx-auto grid max-w-6xl gap-3 px-4 py-8">
        <p>
          Prices from{" "}
          {stores.map((s, i) => (
            <span key={s.slug}>
              {i > 0 && (i === stores.length - 1 ? " and " : ", ")}
              <a href={s.base_url} className="underline-offset-4 hover:text-foreground hover:underline">
                {s.name}
              </a>
            </span>
          ))}
          , updated twice a day. Prices in CAD.
        </p>
        <p>Card names and images © Konami. Card Scout CA is not affiliated with Konami or the stores.</p>
      </div>
    </footer>
  );
}
