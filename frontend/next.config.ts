import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    serverActions: {
      // Wedding inquiry inspiration photos can be up to 10 MB.
      bodySizeLimit: "12mb",
    },
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.DJANGO_API_URL ?? "http://localhost:8000"}/api/:path*`,
      },
      {
        source: "/media/:path*",
        destination: `${process.env.DJANGO_API_URL ?? "http://localhost:8000"}/media/:path*`,
      },
    ];
  },
};

export default nextConfig;

import { initOpenNextCloudflareForDev } from "@opennextjs/cloudflare";

if (process.env.SKIP_CLOUDFLARE_DEV_INIT !== "true") {
  initOpenNextCloudflareForDev();
}
