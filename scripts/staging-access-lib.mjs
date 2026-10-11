import { checkStaging, stagingAccessHeaders, stagingOrigin } from "./staging-smoke-lib.mjs";

export function validateAccessDenial(response) {
  if ([401, 403].includes(response.status)) return;
  if (response.status === 302) {
    const location = new URL(response.headers.get("location") || "/", stagingOrigin);
    if (location.origin === "https://cool-thunder-025c.cloudflareaccess.com" &&
        location.pathname.startsWith("/cdn-cgi/access/login")) return;
  }
  throw new Error("Staging must deny unauthenticated/invalid-token access, not serve the site or fail upstream.");
}

export async function checkStagingAccess(fetcher = fetch, access) {
  // Validate without exposing values, before any requests.
  stagingAccessHeaders(access);
  for (const headers of [
    { "Cache-Control": "no-cache" },
    stagingAccessHeaders({ clientId: access.clientId, clientSecret: "deliberately-invalid-staging-probe" }),
  ]) {
    for (const path of ["/", "/api/health/"]) {
      const response = await fetcher(`${stagingOrigin}${path}`, {
        headers: { ...headers }, redirect: "manual", signal: AbortSignal.timeout(20_000),
      });
      validateAccessDenial(response);
      await response.body?.cancel();
    }
  }
  return checkStaging(fetcher, access);
}
