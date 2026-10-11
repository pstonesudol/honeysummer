import { releaseOriginHeaders } from "./origin-auth.mjs";
import { targets, validateSmoke } from "./release-lib.mjs";

try {
  const headers = releaseOriginHeaders("staging", process.env.STAGING_ORIGIN_SECRET);
  const origin = targets.staging.origin;
  for (const requestHeaders of [{}, { "X-HoneySummer-Origin-Secret": "deliberately-invalid-origin-probe" }]) {
    for (const path of ["/admin/login", "/api/retail/flowers/", "/media/origin-probe-missing.jpg"]) {
      const response = await fetch(`${origin}${path}`, {
        headers: { "Cache-Control": "no-cache", ...requestHeaders }, redirect: "manual",
        signal: AbortSignal.timeout(15_000),
      });
      if (response.status !== 403 || (await response.json()).detail !== "Origin access denied.") {
        throw new Error("Origin gate denial failed.");
      }
    }
  }
  const response = await fetch(`${origin}/api/retail/flowers/`, {
    headers, redirect: "error", signal: AbortSignal.timeout(15_000),
  });
  validateSmoke("/api/retail/flowers/", response.status, await response.json());
  console.log("Direct staging origin: missing/wrong secrets denied; authorized catalogue passed. No deployment performed.");
} catch {
  console.error("Staging origin gate verification failed; check configuration and availability. No deployment performed.");
  process.exitCode = 1;
}
