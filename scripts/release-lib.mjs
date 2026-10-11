import { createHash } from "node:crypto";

export const projectId = "f6a6b452-3e27-43fa-badb-c6a95d4de2cd";
export const serviceId = "340c4738-0456-42f0-aa68-cb2500881f26";
export const targets = {
  staging: {
    id: "1084c402-f444-49e4-8a85-3ac85e82bf5d",
    origin: "https://honeysummer-staging.up.railway.app",
  },
  production: {
    id: "9124ee23-06b5-49bd-a740-5975d2066690",
    origin: "https://honeysummer-production.up.railway.app",
  },
};

export function digest(source) {
  return createHash("sha256").update(source).digest("hex");
}

export function validatePromotion(receipt, sha, sourceDigest) {
  if (!/^[a-f0-9]{40}$/.test(sha) || receipt.sha !== sha ||
      receipt.archiveSha256 !== sourceDigest || receipt.environment !== "staging" ||
      receipt.status !== "SUCCESS" || receipt.smoke !== "passed" ||
      receipt.environmentId !== targets.staging.id || receipt.serviceId !== serviceId ||
      !receipt.deploymentId) {
    throw new Error("Production requires the matching successful staging receipt and unchanged source archive.");
  }
}

export function validateDeployment(deployment, environmentId) {
  if (deployment.environmentId !== environmentId || deployment.serviceId !== serviceId ||
      deployment.projectId !== projectId) {
    throw new Error("Railway returned a deployment for a different target.");
  }
  if (["FAILED", "CRASHED", "REMOVED", "SKIPPED", "CANCELLED"].includes(deployment.status)) {
    throw new Error(`Deployment ${deployment.id} ${deployment.status}; production promotion is blocked.`);
  }
  return deployment.status === "SUCCESS";
}

export function validateSmoke(path, status, body) {
  if (status !== 200) throw new Error(`Smoke check ${path} returned HTTP ${status}.`);
  if (path === "/api/health/") {
    if (body.status !== "ok" || body.service !== "honey-summer-api") {
      throw new Error("Unexpected API health response.");
    }
  } else if (!Array.isArray(body)) {
    throw new Error(`Unexpected catalogue response for ${path}.`);
  }
}
