/** Server/Worker-only origin credentials. Never import into a client component. */
export const originSecretHeader = "X-HoneySummer-Origin-Secret";

export function originAuthHeaders(env: {
  DEPLOYMENT_ENVIRONMENT?: string;
  STAGING_ORIGIN_SECRET?: string;
}): Record<string, string> {
  // Never inject the staging credential into production or local requests.
  if (env.DEPLOYMENT_ENVIRONMENT !== "staging" || !env.STAGING_ORIGIN_SECRET) return {};
  if (!/^[A-Za-z0-9_-]{43,128}$/.test(env.STAGING_ORIGIN_SECRET)) {
    throw new Error("Invalid staging origin credential configuration.");
  }
  return { [originSecretHeader]: env.STAGING_ORIGIN_SECRET };
}
