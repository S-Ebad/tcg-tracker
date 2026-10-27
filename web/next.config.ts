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
  // card images come from our API (which downloads each once and serves its own copy)
  async rewrites() {
    return [{ source: "/images/:key", destination: `${API_URL}/images/:key` }];
  },
};

export default nextConfig;
