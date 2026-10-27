import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // Card images come from our API (which downloads each once and serves its own copy); the search box's suggestions
  // call the API's search from the browser through the same origin, so the API needs no CORS setup.
  async rewrites() {
    return [
      { source: "/images/:key", destination: `${API_URL}/images/:key` },
      { source: "/api/search", destination: `${API_URL}/api/search` },
    ];
  },
};

export default nextConfig;
