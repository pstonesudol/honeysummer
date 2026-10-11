import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { workerConfig } from "./worker-config.mjs";

const directory = fileURLToPath(new URL("../", import.meta.url));
const generated = fileURLToPath(new URL("../.wrangler-release.json", import.meta.url));
const lock = fileURLToPath(new URL("../.worker-build-lock", import.meta.url));

function run(args, env) {
  const result = spawnSync("opennextjs-cloudflare", args, {
    cwd: directory,
    env,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`OpenNext exited with status ${result.status ?? "unknown"}.`);
}

let locked = false;
try {
  const [command, environment, ...extra] = process.argv.slice(2);
  if (!["build", "preview", "deploy", "upload"].includes(command) || extra.length) {
    throw new Error("Usage: worker.mjs build|preview|deploy|upload staging|production (no extra flags).");
  }
  const { config, target, vars } = workerConfig(environment, process.env);
  // Next/OpenNext outputs are shared: never reuse a build from another target,
  // or run two environment builds concurrently in the same checkout.
  mkdirSync(lock);
  locked = true;
  writeFileSync(generated, JSON.stringify(config, null, 2));
  const env = { ...process.env, ...vars, SKIP_CLOUDFLARE_DEV_INIT: "true" };
  const args = ["--config", generated, "--env", environment];
  console.log(`Worker: ${target.name}; backend: ${vars.API_URL}; storefront: ${vars.NEXT_PUBLIC_SITE_URL}`);
  run(["build", ...args], env);
  if (command !== "build") run([command, ...args], env);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  if (locked) {
    rmSync(generated, { force: true });
    rmSync(lock, { recursive: true });
  }
}
