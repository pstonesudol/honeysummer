import { test } from "node:test";
import assert from "node:assert/strict";
import { digest, projectId, serviceId, targets, validateDeployment, validatePromotion,
  validateSmoke } from "../release-lib.mjs";

const sha = "a".repeat(40);
const hash = digest("source");
const receipt = { sha, archiveSha256: hash, environment: "staging", environmentId: targets.staging.id,
  serviceId, deploymentId: "staging-deploy", status: "SUCCESS", smoke: "passed" };

test("production accepts only the same staging-verified SHA and archive", () => {
  validatePromotion(receipt, sha, hash);
  for (const changed of [{ sha: "b".repeat(40) }, { archiveSha256: digest("changed") },
    { status: "FAILED" }, { smoke: "failed" }, { environment: "production" },
    { environmentId: targets.production.id }, { serviceId: "other" }, { deploymentId: null }]) {
    assert.throws(() => validatePromotion({ ...receipt, ...changed }, sha, hash));
  }
  assert.throws(() => validatePromotion(receipt, "main", hash));
});

test("a different or failed deployment cannot open the promotion gate", () => {
  const deployment = { id: "one", projectId, serviceId, environmentId: targets.staging.id, status: "SUCCESS" };
  assert.equal(validateDeployment(deployment, targets.staging.id), true);
  assert.equal(validateDeployment({ ...deployment, status: "BUILDING" }, targets.staging.id), false);
  for (const changed of [{ status: "FAILED" }, { status: "CRASHED" }, { status: "REMOVED" },
    { projectId: "other" }, { serviceId: "other" }, { environmentId: targets.production.id }]) {
    assert.throws(() => validateDeployment({ ...deployment, ...changed }, targets.staging.id));
  }
});

test("smoke checks reject bad HTTP responses, wrong services and invalid DB-backed catalogues", () => {
  validateSmoke("/api/health/", 200, { status: "ok", service: "honey-summer-api" });
  validateSmoke("/api/retail/flowers/", 200, []);
  assert.throws(() => validateSmoke("/api/health/", 503, {}));
  assert.throws(() => validateSmoke("/api/health/", 200, { status: "ok", service: "other" }));
  assert.throws(() => validateSmoke("/api/retail/flowers/", 200, { error: "database unavailable" }));
});
