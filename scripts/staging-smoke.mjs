import { readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { checkStaging, stagingOrigin } from "./staging-smoke-lib.mjs";

try {
  const [directory, ...extra] = process.argv.slice(2);
  const sha = process.env.RELEASE_SHA;
  if (!directory || extra.length || !/^[a-f0-9]{40}$/.test(sha ?? "")) {
    throw new Error("Provide an artifact directory and the 40-character RELEASE_SHA.");
  }
  const artifact = resolve(directory);
  const backend = JSON.parse(readFileSync(join(artifact, "staging.json"), "utf8"));
  if (backend.sha !== sha || backend.environment !== "staging" || backend.smoke !== "passed") {
    throw new Error("Staging proxy checks require this commit's successful backend receipt.");
  }
  const paths = await checkStaging();
  writeFileSync(join(artifact, "staging-frontend.json"), JSON.stringify({
    sha, environment: "staging", worker: "honey-summer-staging", origin: stagingOrigin,
    smoke: "passed", paths, verifiedAt: new Date().toISOString(),
  }, null, 2));
  if (process.env.GITHUB_STEP_SUMMARY) {
    writeFileSync(process.env.GITHUB_STEP_SUMMARY,
      `## Staging frontend/proxy verified\nCommit: \`${sha}\`\nOrigin: ${stagingOrigin}\n` +
      `Read-only checks: ${paths.join(", ")}.\nNo sign-in, form submission or private-media acceptance implied.\n` +
      `Production promotion remains backend-only.\n`, { flag: "a" });
  }
  console.log("Staging storefront/proxy/admin-entry checks passed; production frontend is not enabled.");
} catch (error) {
  // Provider responses may contain sensitive values; don't print raw bodies/errors.
  console.error("Staging frontend/proxy verification failed; production promotion is blocked.");
  process.exitCode = 1;
}
