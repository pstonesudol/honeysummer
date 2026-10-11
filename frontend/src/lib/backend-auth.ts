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
    // Build/local Node context has no Worker secret. Never bake one into a build.
    env = { DEPLOYMENT_ENVIRONMENT: process.env.DEPLOYMENT_ENVIRONMENT };
  }
  return originAuthHeaders(env);
}
