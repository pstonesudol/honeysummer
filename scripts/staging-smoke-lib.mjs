import { validateSmoke } from "./release-lib.mjs";

export const stagingOrigin = "https://staging.hellohoneysummer.com";
export const smokePaths = ["/", "/order-flowers", "/api/health/", "/api/retail/flowers/", "/admin/login", "/admin/"];

export function validateStagingResponse(path, response, body) {
  if (!smokePaths.includes(path)) throw new Error("Unknown staging smoke path.");
  if (path === "/admin/") {
    if (response.status !== 302 || response.headers.get("location") !== "/admin/login" ||
        response.headers.get("cache-control") !== "no-store") {
      throw new Error("Anonymous admin access must preserve the backend login redirect without caching it.");
    }
    return;
  }
  if (response.status !== 200 || response.redirected) {
    throw new Error(`Staging ${path} must return HTTP 200 without redirects.`);
  }
  const type = response.headers.get("content-type") ?? "";
  if (path.startsWith("/api/")) {
    if (!type.includes("application/json")) throw new Error(`Staging ${path} did not return JSON.`);
    validateSmoke(path, response.status, JSON.parse(body));
    return;
  }
  if (!type.includes("text/html")) throw new Error(`Staging ${path} did not return HTML.`);
  if (!/<title>[^<]*Honey Summer/i.test(body)) throw new Error(`Staging ${path} returned an unexpected page.`);
  if (path === "/" || path === "/order-flowers") {
    const robots = body.match(/<meta\b[^>]*>/gi)?.find(tag => /\bname=["']robots["']/i.test(tag));
    if (!robots || !/\bcontent=["'][^"']*\bnoindex\b/i.test(robots)) {
      throw new Error(`Staging ${path} is missing noindex metadata.`);
    }
  }
  if (path === "/admin/login") {
    if (!/\btype=["']password["']/i.test(body) || !/\bname=["']csrf_token["']/i.test(body)) {
      throw new Error("Staging admin login form is missing password/CSRF fields.");
    }
    // Only check cookie attributes; never log or retain their token values.
    for (const name of ["honeysummer_csrf", "honeysummer_security_csrf"]) {
      const cookie = response.headers.getSetCookie().find(value => value.startsWith(`${name}=`));
      if (!cookie || !/;\s*Secure(?:;|$)/i.test(cookie) ||
          !/;\s*HttpOnly(?:;|$)/i.test(cookie) || !/;\s*SameSite=Lax(?:;|$)/i.test(cookie)) {
        throw new Error(`Staging ${name} cookie is missing required security attributes.`);
      }
    }
  }
}

export function stagingAccessHeaders({ clientId, clientSecret } = {}) {
  for (const value of [clientId, clientSecret]) {
    if (typeof value !== "string" || !value || /[\s:"']/.test(value)) {
      throw new Error("Access credentials must be raw nonempty values, without header prefixes or whitespace.");
    }
  }
  return {
    "Cache-Control": "no-cache",
    "CF-Access-Client-Id": clientId,
    "CF-Access-Client-Secret": clientSecret,
  };
}

export async function checkStaging(fetcher = fetch, access) {
  const headers = stagingAccessHeaders(access);
  for (const path of smokePaths) {
    const response = await fetcher(`${stagingOrigin}${path}`, {
      // Fixed staging origin only. Never follow a redirect with these secrets.
      redirect: "manual", headers: { ...headers },
      signal: AbortSignal.timeout(20_000),
    });
    validateStagingResponse(path, response, await response.text());
  }
  return smokePaths;
}
