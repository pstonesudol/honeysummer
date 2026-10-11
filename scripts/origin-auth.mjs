export function releaseOriginHeaders(environment, secret) {
  if (environment !== "staging") return { "Cache-Control": "no-cache" };
  if (typeof secret !== "string" || !/^[A-Za-z0-9_-]{43,128}$/.test(secret)) {
    throw new Error("Staging requires a valid environment-scoped STAGING_ORIGIN_SECRET.");
  }
  return { "Cache-Control": "no-cache", "X-HoneySummer-Origin-Secret": secret };
}
