import "server-only";
import { getCloudflareContext } from "@opennextjs/cloudflare";
import { originAuthHeaders } from "./origin-auth";

declare global {
  interface CloudflareEnv {
    DEPLOYMENT_ENVIRONMENT?: string;
    STAGING_ORIGIN_SECRET?: string;
  }
}

export function backendAuthHeaders(): Record<string, string> {
  let env;
  try {
    env = getCloudflareContext().env;
  } catch {
    // Some OpenNext server execution paths may not expose the synchronous
    // request context. Runtime Worker vars are populated into process.env by
    // OpenNext; never provide these as build-time/public variables.
    env = {
      DEPLOYMENT_ENVIRONMENT: process.env.DEPLOYMENT_ENVIRONMENT,
      STAGING_ORIGIN_SECRET: process.env.STAGING_ORIGIN_SECRET,
    };
  }
  return originAuthHeaders(env);
}
