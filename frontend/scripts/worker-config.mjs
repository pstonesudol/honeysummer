import { readFileSync } from "node:fs";

const source = new URL("../wrangler.jsonc", import.meta.url);

function httpsOrigin(value, label) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${label} must be a valid HTTPS origin.`);
  }
  if (parsed.protocol !== "https:" || parsed.username || parsed.password ||
      parsed.pathname !== "/" || parsed.search || parsed.hash ||
      parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1" ||
      parsed.hostname === "[::1]") {
    throw new Error(`${label} must be an HTTPS origin without credentials, paths or query strings.`);
  }
  return parsed.origin;
}

export function workerConfig(environment, overrides = {}) {
  if (!["staging", "production"].includes(environment)) {
    throw new Error("Choose staging or production explicitly; use build:staging or build:production.");
  }
  const config = JSON.parse(readFileSync(source, "utf8"));
  const target = config.env[environment];
  const api = httpsOrigin(overrides.API_URL || target.vars.API_URL, "API_URL");
  const site = httpsOrigin(overrides.NEXT_PUBLIC_SITE_URL || target.vars.NEXT_PUBLIC_SITE_URL,
    "NEXT_PUBLIC_SITE_URL");
  const stagingApi = config.env.staging.vars.API_URL;
  if (environment === "staging" && api !== stagingApi) {
    throw new Error("Staging must use its configured staging backend, not a production/local backend.");
  }
  if (environment === "production" && (api === stagingApi || api === site ||
      api.includes("staging") || site !== "https://hellohoneysummer.com")) {
    throw new Error("Production requires its own backend and https://hellohoneysummer.com storefront.");
  }
  if (environment === "staging" && site === "https://hellohoneysummer.com") {
    throw new Error("Staging must not use the production storefront origin.");
  }
  target.vars.API_URL = api;
  target.vars.NEXT_PUBLIC_SITE_URL = site;
  return { config, target, vars: target.vars };
}
