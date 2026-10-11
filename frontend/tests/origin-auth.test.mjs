import { test } from "node:test";
import assert from "node:assert/strict";
import { originAuthHeaders, originSecretHeader } from "../src/lib/origin-auth.ts";
import { proxyBackend } from "../scripts/backend-proxy.mjs";

const secret = "synthetic_" + "a".repeat(43);

test("origin secret is injected only from staging runtime configuration", () => {
  assert.deepEqual(originAuthHeaders({ DEPLOYMENT_ENVIRONMENT: "staging", STAGING_ORIGIN_SECRET: secret }),
    { [originSecretHeader]: secret });
  for (const DEPLOYMENT_ENVIRONMENT of [undefined, "production", "local"]) {
    assert.deepEqual(originAuthHeaders({ DEPLOYMENT_ENVIRONMENT, STAGING_ORIGIN_SECRET: secret }), {});
  }
  assert.deepEqual(originAuthHeaders({ DEPLOYMENT_ENVIRONMENT: "staging" }), {});
  assert.throws(() => originAuthHeaders({ DEPLOYMENT_ENVIRONMENT: "staging", STAGING_ORIGIN_SECRET: "short" }));
});

test("client origin headers are stripped, then overwritten only with trusted configuration", async () => {
  for (const configured of [{}, { [originSecretHeader]: secret }]) {
    await proxyBackend(new Request("https://staging.hellohoneysummer.com/admin/login", {
      headers: { [originSecretHeader]: "attacker-value", Origin: "https://staging.hellohoneysummer.com" },
    }), "https://honeysummer-staging.up.railway.app", async request => {
      assert.equal(request.headers.get(originSecretHeader), configured[originSecretHeader] ?? null);
      assert.equal(request.redirect, "manual");
      return new Response("ok");
    }, configured);
  }
});
