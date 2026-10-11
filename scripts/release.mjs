import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { setTimeout as wait } from "node:timers/promises";
import { digest, projectId, serviceId, targets, validateDeployment, validatePromotion,
  validateSmoke } from "./release-lib.mjs";

function command(args, options = {}) {
  const result = spawnSync(args[0], args.slice(1), {
    encoding: "utf8", timeout: 120_000, maxBuffer: 32 * 1024 * 1024, ...options,
  });
  // Avoid dumping raw provider output/credentials into CI logs.
  if (result.error || result.status !== 0) throw new Error(`${args[0]} command failed; inspect the provider dashboard.`);
  return result.stdout;
}

function deployment(id) {
  const query = "query($id: String!) { deployment(id: $id) { id status projectId environmentId serviceId } }";
  const response = JSON.parse(command(["railway", "api", query, "--variables", JSON.stringify({ id })]));
  if (response.errors?.length || !response.data?.deployment) throw new Error("Deployment status could not be verified.");
  return response.data.deployment;
}

let temporary;
try {
  const [environment, directory, ...extra] = process.argv.slice(2);
  const target = targets[environment];
  const sha = process.env.RELEASE_SHA;
  if (!target || !directory || extra.length || !/^[a-f0-9]{40}$/.test(sha ?? "")) {
    throw new Error("Usage: RELEASE_SHA=<40-character SHA> node scripts/release.mjs staging|production artifact-directory");
  }
  if (!process.env.RAILWAY_TOKEN) throw new Error("Missing environment-scoped RAILWAY_TOKEN.");
  const head = command(["git", "rev-parse", "HEAD"]).trim();
  if (head !== sha) throw new Error("Checkout does not match the CI-tested commit.");
  const artifact = resolve(directory);
  const archive = readFileSync(join(artifact, "backend.tar"));
  const archiveSha256 = digest(archive);
  // Verify the archive is exactly the tracked backend of the checked-out SHA.
  const expected = command(["git", "archive", "--format=tar", sha, "backend"], { encoding: null });
  if (digest(expected) !== archiveSha256) throw new Error("Source archive differs from the approved commit.");
  if (environment === "production") {
    validatePromotion(JSON.parse(readFileSync(join(artifact, "staging.json"), "utf8")), sha, archiveSha256);
  }
  temporary = mkdtempSync(join(tmpdir(), "honeysummer-release-"));
  command(["tar", "-xf", join(artifact, "backend.tar"), "-C", temporary]);
  const upload = JSON.parse(command([
    "railway", "up", temporary, "--path-as-root", "--detach", "--json",
    "--project", projectId, "--environment", target.id, "--service", serviceId,
    "--message", `Release ${sha} (${environment})`,
  ]));
  if (!upload.deploymentId) throw new Error("Railway did not return an exact deployment ID; do not blindly retry.");
  const id = upload.deploymentId;
  console.log(`Waiting for ${environment} deployment ${id} of ${sha}`);
  const deadline = Date.now() + 15 * 60_000;
  let healthy = false;
  while (Date.now() < deadline) {
    if (validateDeployment(deployment(id), target.id)) { healthy = true; break; }
    await wait(10_000);
  }
  if (!healthy) throw new Error("Deployment timed out; review the exact ID before retrying.");
  // Read-only smoke checks: health plus a real DB-backed catalogue query.
  for (const path of ["/api/health/", "/api/retail/flowers/"]) {
    const response = await fetch(`${target.origin}${path}`, {
      headers: { "Cache-Control": "no-cache" },
      redirect: "error", signal: AbortSignal.timeout(15_000),
    });
    validateSmoke(path, response.status, await response.json());
  }
  // Confirm the precise deployment is still successful after the smoke checks.
  if (!validateDeployment(deployment(id), target.id)) throw new Error("Deployment is no longer successful.");
  const receipt = { sha, archiveSha256, environment, environmentId: target.id, serviceId,
    deploymentId: id, status: "SUCCESS", smoke: "passed", verifiedAt: new Date().toISOString() };
  writeFileSync(join(artifact, `${environment}.json`), JSON.stringify(receipt, null, 2));
  if (process.env.GITHUB_STEP_SUMMARY) {
    writeFileSync(process.env.GITHUB_STEP_SUMMARY,
      `## ${environment} backend verified\nCommit: \`${sha}\`\nDeployment: \`${id}\`\nRead-only health/catalogue checks passed.\n`,
      { flag: "a" });
  }
  console.log(`${environment} verified. No frontend, payment, email or launch acceptance is implied.`);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  if (temporary) rmSync(temporary, { recursive: true });
}
