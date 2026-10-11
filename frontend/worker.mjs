import nextWorker from "./.open-next/worker.js";
import { isBackendPath, proxyBackend } from "./scripts/backend-proxy.mjs";
import { originAuthHeaders } from "./src/lib/origin-auth.ts";

// Keep OpenNext's generated exports/handlers; intercept backend routes before
// its external-rewrite fetch proxy can follow redirects and lose Set-Cookie.
export * from "./.open-next/worker.js";
const worker = {
  ...nextWorker,
  async fetch(request, env, ctx) {
    if (!isBackendPath(new URL(request.url).pathname)) {
      return nextWorker.fetch(request, env, ctx);
    }
    try {
      return await proxyBackend(request, env.API_URL, fetch, originAuthHeaders(env));
    } catch {
      // Never include request bodies, cookies, credentials or provider errors.
      return new Response("Backend unavailable.", {
        status: 502,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
    }
  },
};

export default worker;
