import type { NextConfig } from "next";

const apiUrl = (process.env.API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

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
        destination: `${apiUrl}/api/:path*`,
      },
      {
        source: "/media/:path*",
        destination: `${apiUrl}/media/:path*`,
      },
      // The admin lives on the backend service; proxy it so it is reachable on
      // the site's own origin as well as directly on the API port.
      {
        source: "/admin",
        destination: `${apiUrl}/admin`,
      },
      {
        source: "/admin/:path*",
        destination: `${apiUrl}/admin/:path*`,
      },
    ];
  },
};

export default nextConfig;

import { initOpenNextCloudflareForDev } from "@opennextjs/cloudflare";

if (process.env.SKIP_CLOUDFLARE_DEV_INIT !== "true") {
  initOpenNextCloudflareForDev();
}
