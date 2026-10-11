import { appendFileSync } from "node:fs";
import { checkStagingAccess } from "./staging-access-lib.mjs";

try {
  await checkStagingAccess(fetch, {
    clientId: process.env.CF_ACCESS_CLIENT_ID,
    clientSecret: process.env.CF_ACCESS_CLIENT_SECRET,
  });
  const summary = "Staging Access: anonymous and invalid-token requests denied; valid CI token passed all storefront/API/admin-entry probes. Read-only: no deploy or production operation. Alternate origins are not certified by this check.";
  console.log(summary);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`);
} catch {
  // Do not print transport errors, bodies, Locations or credential values.
  console.error("Staging Access verification failed. Review Access policy and staging availability; no deployment performed.");
  process.exitCode = 1;
}
