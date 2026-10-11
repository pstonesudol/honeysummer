import { appendFileSync } from "node:fs";
import { validatePullRequestTitle } from "./pr-title-lib.mjs";

try {
  const { type, scope, breaking } = validatePullRequestTitle(process.env.PR_TITLE);
  const summary = `Pull request title is valid: ${type}${scope ? `(${scope})` : ""}${breaking ? "!" : ""}`;
  console.log(summary);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
